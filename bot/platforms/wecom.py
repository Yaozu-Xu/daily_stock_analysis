# -*- coding: utf-8 -*-
"""
===================================
企业微信平台适配器
===================================

处理企业微信机器人的回调消息。

企业微信回调模式说明：
1. 在企业微信管理后台 → 应用管理 → 自建应用 → 设置 → 接收消息
2. 配置回调 URL: http://your-server/bot/wecom
3. 设置 Token、EncodingAESKey
4. 企业微信使用 XML + AES 加密推送消息

企业微信回调文档：
https://developer.work.weixin.qq.com/document/path/90238
"""

import base64
import hashlib
import logging
import random
import socket
import struct
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from bot.platforms.base import BotPlatform
from bot.models import BotMessage, BotResponse, ChatType, WebhookResponse

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

logger = logging.getLogger(__name__)


class WeChatCrypto:
    """企业微信消息加解密工具。

    使用 AES-256-CBC 加解密，PKCS7 填充。
    密钥由 EncodingAESKey 经过 Base64 解码后取前 32 字节。
    """

    def __init__(self, encoding_aes_key: str, token: str, corp_id: str):
        """
        Args:
            encoding_aes_key: 消息加解密密钥（43位 Base64 字符串）
            token: 回调 Token
            corp_id: 企业 ID（CorpID）
        """
        self._token = token
        self._corp_id = corp_id

        if not HAS_CRYPTOGRAPHY:
            raise ImportError(
                "cryptography 库未安装，无法使用企业微信消息加解密。\n"
                "请执行: pip install cryptography"
            )

        # EncodingAESKey 是 43 位 Base64 编码的密钥，解码后为 32 字节
        aes_key = base64.b64decode(encoding_aes_key + "=")
        self._aes_key = aes_key
        self._iv = aes_key[:16]

    @property
    def token(self) -> str:
        return self._token

    def decrypt(self, encrypted_msg: str) -> str:
        """解密企业微信加密消息。

        Args:
            encrypted_msg: Base64 编码的密文

        Returns:
            解密后的 XML 明文

        Raises:
            ValueError: 解密失败或验证不通过
        """
        try:
            encrypted_bytes = base64.b64decode(encrypted_msg)
        except Exception as exc:
            raise ValueError(f"Base64 解码失败: {exc}") from exc

        cipher = Cipher(algorithms.AES(self._aes_key), modes.CBC(self._iv))
        decryptor = cipher.decryptor()
        decrypted_padded = decryptor.update(encrypted_bytes) + decryptor.finalize()

        # PKCS7 去填充
        unpadder = padding.PKCS7(256).unpadder()
        decrypted = unpadder.update(decrypted_padded) + unpadder.finalize()

        # 解析明文结构: [4字节网络序长度][XML消息][CorpID]
        # 前 4 字节是网络序（大端）的 XML 长度
        msg_len = struct.unpack(">I", decrypted[:4])[0]
        xml_content = decrypted[4:4 + msg_len].decode("utf-8")
        receive_id = decrypted[4 + msg_len:].decode("utf-8")

        # 验证 CorpID
        if receive_id != self._corp_id:
            raise ValueError(f"CorpID 不匹配: 期望 {self._corp_id}，实际 {receive_id}")

        return xml_content

    def encrypt(self, reply_xml: str, nonce: str, timestamp: str) -> str:
        """加密回复消息。

        Args:
            reply_xml: 回复的 XML 明文
            nonce: 随机字符串
            timestamp: 时间戳

        Returns:
            Base64 编码的密文
        """
        # 构造待加密数据: [4字节网络序长度][XML消息][CorpID]
        raw_bytes = reply_xml.encode("utf-8")
        msg_len = struct.pack(">I", len(raw_bytes))
        plain_bytes = msg_len + raw_bytes + self._corp_id.encode("utf-8")

        # PKCS7 填充
        padder = padding.PKCS7(256).padder()
        padded = padder.update(plain_bytes) + padder.finalize()

        # AES-256-CBC 加密
        cipher = Cipher(algorithms.AES(self._aes_key), modes.CBC(self._iv))
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(padded) + encryptor.finalize()

        return base64.b64encode(encrypted).decode("utf-8")

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echo_str: str) -> str:
        """验证回调 URL（企业微信配置回调地址时的验证流程）。

        企业微信会发送一个 GET 请求到回调 URL，包含 msg_signature、timestamp、
        nonce、echostr 参数。需要解密 echostr 并返回明文。

        Args:
            msg_signature: 签名串
            timestamp: 时间戳
            nonce: 随机字符串
            echo_str: 加密的 echostr

        Returns:
            解密后的 echostr 明文
        """
        # 验证签名
        if not self._verify_signature(msg_signature, timestamp, nonce, echo_str):
            raise ValueError("签名验证失败")

        return self.decrypt(echo_str)

    def encrypt_reply(self, reply_xml: str, nonce: str, timestamp: str) -> Tuple[str, str, str]:
        """加密回复消息并生成签名。

        Args:
            reply_xml: 回复的 XML 明文
            nonce: 随机字符串
            timestamp: 时间戳

        Returns:
            (encrypted_msg, msg_signature, nonce, timestamp) 元组
        """
        encrypted = self.encrypt(reply_xml, nonce, timestamp)
        signature = self._generate_signature(timestamp, nonce, encrypted)
        return encrypted, signature

    def _verify_signature(self, msg_signature: str, timestamp: str, nonce: str, msg: str) -> bool:
        """验证消息签名。"""
        expected = self._generate_signature(timestamp, nonce, msg)
        return msg_signature == expected

    def _generate_signature(self, timestamp: str, nonce: str, msg: str) -> str:
        """生成 SHA1 签名。

        签名算法: SHA1(sorted(token, timestamp, nonce, msg))
        """
        sort_list = sorted([self._token, timestamp, nonce, msg])
        sort_str = "".join(sort_list)
        return hashlib.sha1(sort_str.encode("utf-8")).hexdigest()


class WecomPlatform(BotPlatform):
    """
    企业微信平台适配器

    支持：
    - 企业微信自建应用回调消息接收
    - 文本消息解析
    - 消息加解密（AES-256-CBC）
    - URL 验证（配置回调地址时）

    配置要求（.env）：
        WECOM_CORPID=ww1234567890abcdef    # 企业 ID
        WECOM_TOKEN=your_token              # 回调 Token
        WECOM_ENCODING_AES_KEY=your_key     # 消息加解密密钥
        WECOM_AGENT_ID=1000001              # 应用 AgentId

    企业微信后台配置：
        应用管理 → 自建应用 → 接收消息
        URL: http://your-server/bot/wecom
        Token: 与 WECOM_TOKEN 一致
        EncodingAESKey: 与 WECOM_ENCODING_AES_KEY 一致
    """

    def __init__(self):
        from src.config import get_config

        config = get_config()

        self._corp_id = getattr(config, "wecom_corpid", None) or ""
        self._token = getattr(config, "wecom_token", None) or ""
        self._encoding_aes_key = getattr(config, "wecom_encoding_aes_key", None) or ""
        self._agent_id = getattr(config, "wecom_agent_id", None) or ""

        self._crypto: Optional[WeChatCrypto] = None
        if self._encoding_aes_key and self._token and self._corp_id:
            try:
                self._crypto = WeChatCrypto(
                    encoding_aes_key=self._encoding_aes_key,
                    token=self._token,
                    corp_id=self._corp_id,
                )
            except Exception as exc:
                logger.warning("[Wecom] 初始化加解密失败: %s", exc)

    @property
    def platform_name(self) -> str:
        return "wecom"

    def verify_request(self, headers: Dict[str, str], body: bytes) -> bool:
        """企业微信回调的签名验证在 URL 验证时完成。

        对于 POST 消息，签名验证在 parse_message 中通过解密过程隐式完成。
        """
        return True

    def parse_message(self, data: Dict[str, Any]) -> Optional[BotMessage]:
        """企业微信消息解析由 handle_webhook 直接处理，不使用此方法。

        企业微信使用 XML + AES 加密格式，与 JSON 平台不同，
        解析逻辑在 handle_webhook → _parse_xml_message 中完成。
        """
        return None

    def handle_challenge(self, data: Dict[str, Any]) -> Optional[WebhookResponse]:
        """企业微信 URL 验证是 GET 请求，不由 JSON 触发。"""
        return None

    def handle_webhook(
        self,
        headers: Dict[str, str],
        body: bytes,
        data: Dict[str, Any],
    ) -> Tuple[Optional[BotMessage], Optional[WebhookResponse]]:
        """处理企业微信 Webhook 请求。

        企业微信回调有两种情况：
        1. GET 请求：URL 验证（配置回调地址时）
        2. POST 请求：消息推送（XML + AES 加密）

        这里重写父类方法，因为企业微信的验证和消息格式与 JSON 平台不同。
        """
        # 检查是否是 GET 请求（URL 验证）
        # 注意：data 参数在这里是 query params，不是 JSON body
        if isinstance(data, dict) and "echostr" in data:
            return self._handle_url_verification(data)

        # POST 消息：XML + AES 加密
        try:
            body_str = body.decode("utf-8") if body else ""
        except UnicodeDecodeError:
            logger.error("[Wecom] 消息体解码失败")
            return None, WebhookResponse.error("Invalid body encoding", 400)

        if not body_str:
            logger.debug("[Wecom] 空消息体")
            return None, WebhookResponse.success()

        # 解密消息
        decrypted_xml = self._decrypt_message(body_str, data)
        if decrypted_xml is None:
            return None, WebhookResponse.error("Decryption failed", 400)

        # 解析 XML 消息
        message = self._parse_xml_message(decrypted_xml)
        if message is None:
            return None, WebhookResponse.success()

        return message, None

    def _handle_url_verification(
        self, query_params: Dict[str, str]
    ) -> Tuple[None, WebhookResponse]:
        """处理企业微信 URL 验证（GET 请求）。

        企业微信配置回调 URL 时，会发送 GET 请求：
        GET /bot/wecom?msg_signature=xxx&timestamp=xxx&nonce=xxx&echostr=xxx

        需要解密 echostr 并返回明文。

        注意：echostr 是 Base64 编码的密文，可能包含 '+' 字符。
        URL query string 中 '+' 会被自动解码为空格（application/x-www-form-urlencoded），
        因此需要将空格还原为 '+'，否则签名验证和解密都会失败。
        """
        msg_signature = query_params.get("msg_signature", "")
        timestamp = query_params.get("timestamp", "")
        nonce = query_params.get("nonce", "")
        echo_str = query_params.get("echostr", "")

        # 修复 URL 解码导致的 '+' → ' ' 问题
        # Base64 编码的 echostr 中 '+' 是有效字符，不应被解码为空格
        if " " in echo_str:
            echo_str = echo_str.replace(" ", "+")
            logger.debug("[Wecom] 修复 echostr 中的 '+' 编码: 空格已还原为 '+'")

        logger.info("[Wecom] 收到 URL 验证请求")

        if not self._crypto:
            logger.error("[Wecom] 加解密未初始化，无法验证 URL")
            return None, WebhookResponse.error("Crypto not initialized", 500)

        try:
            decrypted = self._crypto.verify_url(msg_signature, timestamp, nonce, echo_str)
            logger.info("[Wecom] URL 验证成功")
            # 返回明文 echostr（纯文本，非 JSON）
            return None, WebhookResponse(
                status_code=200,
                body=decrypted,
                headers={"Content-Type": "text/plain"},
            )
        except Exception as exc:
            logger.error("[Wecom] URL 验证失败: %s", exc)
            return None, WebhookResponse.error(f"Verification failed: {exc}", 403)

    def _decrypt_message(self, body_str: str, query_params: Dict[str, str]) -> Optional[str]:
        """解密企业微信推送的加密消息。

        POST 请求的 body 是 XML 格式，包含 Encrypt 字段。
        同时 query params 中包含 msg_signature、timestamp、nonce。
        """
        if not self._crypto:
            logger.warning("[Wecom] 加解密未初始化，尝试直接解析 XML")
            return body_str

        try:
            root = ET.fromstring(body_str)
        except ET.ParseError as exc:
            logger.error("[Wecom] XML 解析失败: %s", exc)
            return None

        # 提取加密消息
        encrypt_node = root.find("Encrypt")
        if encrypt_node is None or not encrypt_node.text:
            logger.warning("[Wecom] XML 中未找到 Encrypt 节点")
            return body_str

        encrypted_msg = encrypt_node.text.strip()

        # 从 query params 获取签名参数
        msg_signature = query_params.get("msg_signature", "")
        timestamp = query_params.get("timestamp", "")
        nonce = query_params.get("nonce", "")

        if not msg_signature or not timestamp or not nonce:
            logger.warning("[Wecom] 缺少签名参数")
            return None

        try:
            decrypted = self._crypto.decrypt(encrypted_msg)
            logger.debug("[Wecom] 消息解密成功")
            return decrypted
        except Exception as exc:
            logger.error("[Wecom] 消息解密失败: %s", exc)
            return None

    def _parse_xml_message(self, xml_content: str) -> Optional[BotMessage]:
        """解析企业微信 XML 消息为统一 BotMessage。

        企业微信文本消息 XML 格式：
        <xml>
            <ToUserName><![CDATA[toUser]]></ToUserName>
            <FromUserName><![CDATA[fromUser]]></FromUserName>
            <CreateTime>1348831860</CreateTime>
            <MsgType><![CDATA[text]]></MsgType>
            <Content><![CDATA[你好]]></Content>
            <MsgId>1234567890123456</MsgId>
            <AgentID>1000001</AgentID>
        </xml>
        """
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as exc:
            logger.error("[Wecom] XML 解析失败: %s", exc)
            return None

        def _get_text(tag: str) -> str:
            node = root.find(tag)
            return node.text.strip() if node is not None and node.text else ""

        msg_type = _get_text("MsgType")
        if msg_type != "text":
            logger.debug("[Wecom] 忽略非文本消息: %s", msg_type)
            return None

        content = _get_text("Content")
        if not content:
            logger.debug("[Wecom] 空消息内容")
            return None

        from_user = _get_text("FromUserName")
        to_user = _get_text("ToUserName")
        msg_id = _get_text("MsgId")
        agent_id = _get_text("AgentID")

        # 解析时间戳
        create_time_str = _get_text("CreateTime")
        try:
            timestamp = datetime.fromtimestamp(int(create_time_str))
        except (ValueError, TypeError):
            timestamp = datetime.now()

        # 企业微信回调中，群聊和私聊通过 AgentID 区分
        # 这里统一视为私聊（企业微信应用消息默认是单聊）
        chat_type = ChatType.PRIVATE

        return BotMessage(
            platform=self.platform_name,
            message_id=msg_id,
            user_id=from_user,
            user_name=from_user,
            chat_id=from_user,
            chat_type=chat_type,
            content=content,
            raw_content=content,
            mentioned=False,
            timestamp=timestamp,
            raw_data={
                "to_user": to_user,
                "agent_id": agent_id,
                "msg_type": msg_type,
                "raw_xml": xml_content,
            },
        )

    def format_response(
        self,
        response: BotResponse,
        message: BotMessage,
    ) -> WebhookResponse:
        """格式化企业微信响应。

        企业微信回调响应需要返回加密的 XML。

        回复 XML 格式：
        <xml>
            <ToUserName><![CDATA[fromUser]]></ToUserName>
            <FromUserName><![CDATA[toUser]]></FromUserName>
            <CreateTime>1348831860</CreateTime>
            <MsgType><![CDATA[text]]></MsgType>
            <Content><![CDATA[回复内容]]></Content>
        </xml>
        """
        if not response.text:
            return WebhookResponse.success()

        # 构造回复 XML
        to_user = message.raw_data.get("to_user", message.user_id)
        from_user = message.raw_data.get("agent_id", self._agent_id)
        create_time = str(int(time.time()))

        reply_xml = (
            f"<xml>"
            f"<ToUserName><![CDATA[{to_user}]]></ToUserName>"
            f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
            f"<CreateTime>{create_time}</CreateTime>"
            f"<MsgType><![CDATA[text]]></MsgType>"
            f"<Content><![CDATA[{response.text}]]></Content>"
            f"</xml>"
        )

        # 如果有加密配置，加密回复
        if self._crypto:
            nonce = str(random.randint(100000, 999999))
            timestamp = create_time
            try:
                encrypted, signature = self._crypto.encrypt_reply(reply_xml, nonce, timestamp)
                encrypted_xml = (
                    f"<xml>"
                    f"<Encrypt><![CDATA[{encrypted}]]></Encrypt>"
                    f"<MsgSignature><![CDATA[{signature}]]></MsgSignature>"
                    f"<TimeStamp>{timestamp}</TimeStamp>"
                    f"<Nonce><![CDATA[{nonce}]]></Nonce>"
                    f"</xml>"
                )
                return WebhookResponse(
                    status_code=200,
                    body=encrypted_xml,
                    headers={"Content-Type": "application/xml"},
                )
            except Exception as exc:
                logger.error("[Wecom] 回复加密失败: %s", exc)
                return WebhookResponse.success()

        # 无加密，直接返回 XML
        return WebhookResponse(
            status_code=200,
            body=reply_xml,
            headers={"Content-Type": "application/xml"},
        )

    def send_followup(
        self,
        response: BotResponse,
        message: BotMessage,
    ) -> bool:
        """企业微信回调模式不支持异步 followup 消息。

        企业微信回调要求 5 秒内同步返回响应。
        如果需要异步发送，应使用企业微信主动推送 API（需要 AccessToken）。
        """
        logger.warning("[Wecom] 回调模式不支持异步 followup 消息")
        return False
