// StoneVast · Battle of Legendary Monsters · Vote API
// Cloudflare Workers + Workers KV
// 路由:
//   GET  /tally           返回当前所有妖怪票数
//   POST /vote            投票  body: { id: "wukong", boost_token?: "xxx" }
//   GET  /verify/:tg_uid  校验 TG 群成员身份,返回一次性 3x 加成 token
// 防刷:
//   - IP+UA 哈希做指纹,24h 冷却
//   - TG 加成 token 一次性使用,绑定 uid + 指纹
// 开源,无敏感信息, KV 命名空间需在 wrangler.toml 配置

const COOLDOWN_SECONDS = 24 * 60 * 60; // 24h
const BOOST_TOKEN_TTL = 10 * 60;       // 加成 token 10 分钟有效
const BOOST_FACTOR = 3;

// TG Bot 配置(部署时通过 wrangler secret 注入)
// TG_BOT_TOKEN  — secret
// TG_CHAT_ID    — var, e.g. "-1004425841910"

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

const MONSTER_IDS = ['wukong','orochi','fenrir','medusa','bahamut','naga','quetzal','dracula'];

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS });
    }

    try {
      if (url.pathname === '/tally' && request.method === 'GET') {
        return await handleTally(env);
      }
      if (url.pathname === '/vote' && request.method === 'POST') {
        return await handleVote(request, env);
      }
      if (url.pathname.startsWith('/verify/') && request.method === 'GET') {
        const uid = url.pathname.split('/').pop();
        return await handleVerify(uid, request, env);
      }
      if (url.pathname === '/health') {
        return json({ ok: true, ts: Date.now() });
      }
      return json({ error: 'not_found' }, 404);
    } catch (e) {
      return json({ error: 'internal', message: String(e).slice(0, 200) }, 500);
    }
  }
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json', ...CORS },
  });
}

async function fingerprint(request) {
  const ip = request.headers.get('CF-Connecting-IP') || '0.0.0.0';
  const ua = request.headers.get('User-Agent') || '';
  const data = new TextEncoder().encode(`${ip}|${ua}|stonevast-monster-v1`);
  const hash = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, '0')).join('');
}

async function handleTally(env) {
  const tally = {};
  let total = 0;
  for (const id of MONSTER_IDS) {
    const v = parseInt(await env.VOTES.get(`m:${id}`) || '0', 10);
    tally[id] = v;
    total += v;
  }
  return json({ tally, total, ts: Date.now() });
}

async function handleVote(request, env) {
  let body;
  try { body = await request.json(); } catch { return json({ error: 'bad_json' }, 400); }

  const id = String(body.id || '');
  if (!MONSTER_IDS.includes(id)) return json({ error: 'invalid_monster' }, 400);

  const fp = await fingerprint(request);

  // 1. 基础冷却校验
  const cdKey = `cd:${fp}`;
  const last = await env.VOTES.get(cdKey);
  if (last) {
    const elapsed = Math.floor(Date.now() / 1000) - parseInt(last, 10);
    if (elapsed < COOLDOWN_SECONDS) {
      return json({ error: 'cooldown', retry_after: COOLDOWN_SECONDS - elapsed }, 429);
    }
  }

  // 2. 加成 token 校验(可选)
  let weight = 1;
  if (body.boost_token) {
    const tk = await env.VOTES.get(`boost:${body.boost_token}`);
    if (tk) {
      const data = JSON.parse(tk);
      if (data.fp === fp && data.exp > Date.now()) {
        weight = BOOST_FACTOR;
        await env.VOTES.delete(`boost:${body.boost_token}`); // 一次性
      }
    }
  }

  // 3. 计票
  const cur = parseInt(await env.VOTES.get(`m:${id}`) || '0', 10);
  await env.VOTES.put(`m:${id}`, String(cur + weight));
  await env.VOTES.put(cdKey, String(Math.floor(Date.now() / 1000)), { expirationTtl: COOLDOWN_SECONDS });

  return json({ ok: true, id, weight, votes: cur + weight });
}

async function handleVerify(uid, request, env) {
  if (!/^\d{5,20}$/.test(uid)) return json({ error: 'invalid_uid' }, 400);
  if (!env.TG_BOT_TOKEN || !env.TG_CHAT_ID) return json({ error: 'tg_not_configured' }, 500);

  // 调 TG getChatMember
  const tgUrl = `https://api.telegram.org/bot${env.TG_BOT_TOKEN}/getChatMember?chat_id=${env.TG_CHAT_ID}&user_id=${uid}`;
  const r = await fetch(tgUrl);
  const data = await r.json();
  if (!data.ok) return json({ error: 'tg_api', detail: data.description }, 502);

  const status = data.result.status; // creator/administrator/member/restricted/left/kicked
  if (!['creator','administrator','member','restricted'].includes(status)) {
    return json({ error: 'not_member', status }, 403);
  }

  // 签发一次性加成 token
  const fp = await fingerprint(request);
  const token = crypto.randomUUID();
  await env.VOTES.put(`boost:${token}`, JSON.stringify({
    uid, fp, exp: Date.now() + BOOST_TOKEN_TTL * 1000,
  }), { expirationTtl: BOOST_TOKEN_TTL });

  return json({ ok: true, boost_token: token, weight: BOOST_FACTOR, ttl: BOOST_TOKEN_TTL });
}
