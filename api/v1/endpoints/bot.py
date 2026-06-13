# -*- coding: utf-8 -*-
"""
===================================
Bot Webhook 路由
===================================

为各平台机器人提供 Webhook 回调端点。

企业微信特殊处理：
- GET 请求：URL 验证（配置回调地址时）
- POST 请求：消息推送（XML + AES 加密）
"""

import logging
from typing import Dict

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response

from bot.handler import (
    handle_dingtalk_webhook,
    handle_feishu_webhook,
    handle_wecom_webhook,
    handle_telegram_webhook,
    handle_webhook_async,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bot", tags=["Bot"])


def _webhook_response_to_fastapi(wr) -> Response:
    """将 WebhookResponse 转换为 FastAPI Response。

    WebhookResponse.body 可能是 dict（JSON）或 str（XML/纯文本）。
    """
    if isinstance(wr.body, dict):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=wr.status_code,
            content=wr.body,
            headers=wr.headers,
        )
    # 字符串 body：XML 或纯文本
    content_type = wr.headers.get("Content-Type", "")
    if "xml" in content_type:
        return Response(
            content=wr.body,
            status_code=wr.status_code,
            media_type="application/xml",
            headers=wr.headers,
        )
    return PlainTextResponse(
        content=wr.body,
        status_code=wr.status_code,
        headers=wr.headers,
    )


@router.api_route("/wecom", methods=["GET", "POST"], include_in_schema=False)
async def wecom_webhook(request: Request):
    """企业微信 Webhook 回调。

    GET 请求：URL 验证（配置回调地址时由企业微信后台发起）。
    POST 请求：接收用户发送的消息（XML + AES 加密）。
    """
    headers = dict(request.headers)
    body = await request.body()

    try:
        if request.method == "GET":
            # GET 请求：URL 验证
            # 将 query params 作为 data 传入
            query_params: Dict[str, list] = dict(request.query_params)
            wr = handle_webhook_async(
                "wecom",
                headers,
                body,
                query_params=query_params,
            )
            # handle_webhook_async 返回 coroutine，需要 await
            wr = await wr
            return _webhook_response_to_fastapi(wr)

        # POST 请求：消息推送
        query_params: Dict[str, list] = dict(request.query_params)
        wr = await handle_webhook_async(
            "wecom",
            headers,
            body,
            query_params=query_params,
        )
        return _webhook_response_to_fastapi(wr)
    except Exception as exc:
        logger.error("[Wecom] Webhook 处理异常: %s", exc, exc_info=True)
        # 返回详细错误信息以便调试
        return PlainTextResponse(
            content=f"Error: {exc}",
            status_code=500,
        )


@router.post("/dingtalk", include_in_schema=False)
async def dingtalk_webhook(request: Request):
    """钉钉 Webhook 回调。"""
    headers = dict(request.headers)
    body = await request.body()
    wr = handle_dingtalk_webhook(headers, body)
    return _webhook_response_to_fastapi(wr)


@router.post("/feishu", include_in_schema=False)
async def feishu_webhook(request: Request):
    """飞书 Webhook 回调。"""
    headers = dict(request.headers)
    body = await request.body()
    wr = handle_feishu_webhook(headers, body)
    return _webhook_response_to_fastapi(wr)


@router.post("/telegram", include_in_schema=False)
async def telegram_webhook(request: Request):
    """Telegram Webhook 回调。"""
    headers = dict(request.headers)
    body = await request.body()
    wr = handle_telegram_webhook(headers, body)
    return _webhook_response_to_fastapi(wr)
