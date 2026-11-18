#!/usr/bin/env python3
# -*- coding: utf-8 -*-


class PayoutAdapter(object):
    """只读采集合约；实现必须经链文档与已知交易核验后才能标为 full。"""

    verification_level = "unverified"

    def collect(self, config):
        raise NotImplementedError("a verified read-only adapter is required")


class AdapterUnavailable(Exception):
    pass


class UnconfiguredAdapter(PayoutAdapter):
    def collect(self, config):
        raise AdapterUnavailable("chain adapter is not configured")


class UnsupportedAdapter(PayoutAdapter):
    def collect(self, config):
        raise AdapterUnavailable("chain adapter is not supported")


def build_default_adapters(configs, environ=None):
    """不猜测任何真实链 API；未核验的适配器保持显式不可用。"""

    return {}
