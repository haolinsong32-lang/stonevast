# StoneVast Monsters Vote · Cloudflare Workers

投票后端,真实全局票仓。免费层(每天 10 万请求)够用。

## 一次性部署

```bash
npm i -g wrangler
wrangler login                                   # 浏览器授权
wrangler kv:namespace create VOTES               # 记录返回的 id 和 preview_id
# 把 id / preview_id 填进 wrangler.toml
wrangler secret put TG_BOT_TOKEN                 # 粘贴 bot token
wrangler deploy                                  # 上线,得到 *.workers.dev 域名
```

## API

| Method | Path | 说明 |
|---|---|---|
| GET | `/tally` | 返回 `{ tally, total }` |
| POST | `/vote` | body `{ id, boost_token? }` |
| GET | `/verify/:tg_uid` | 校验 TG 群成员,返回一次性 `boost_token`(3x) |
| GET | `/health` | 心跳 |

## 防刷

- IP + UA 哈希 → 24h 冷却,写 KV `cd:*`
- 加成 token 一次性使用,绑定 IP 指纹 + 10 分钟过期
- 不收集邮箱/姓名,合规干净

## 自定义域名(可选)

Cloudflare Dashboard → Workers → stonevast-monsters-vote → Triggers → Custom Domains → 加 `api-monsters.stonevast.com`(要求 stonevast.com NS 托管在 Cloudflare)。

如果不动 NS,前端直接用 `*.workers.dev` 默认域名就行。
