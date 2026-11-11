#  RSS to Telegram Bot
#  Copyright (C) 2026 Rongrong <i@rong.moe>
#  Bot API 10.4 extension (Widgets & Ephemeral messages)

from __future__ import annotations
from typing import Optional, Union, Any
import html
import zlib
import aiohttp
from aiohttp_socks import ProxyConnector

from .. import env, log

logger = log.getLogger('RSStT.bot_api')

_API_BASE = 'https://api.telegram.org/bot{token}/{method}'


def _get_api_url(method: str) -> Optional[str]:
    if not env.TOKEN:
        return None
    return _API_BASE.format(token=env.TOKEN, method=method)


def _get_connector() -> Optional[ProxyConnector]:
    proxy = env.R_PROXY
    if proxy:
        proxy_url = proxy.replace('socks5h', 'socks5').replace('socks4a', 'socks4')
        return ProxyConnector.from_url(proxy_url)
    return None


async def call_bot_api(method: str, payload: dict[str, Any], timeout: int = 20) -> Optional[dict]:
    """
    Call Telegram Bot HTTP API (e.g. for Bot API 10.4 features like sendWidget or ephemeral replies)
    """
    url = _get_api_url(method)
    if not url:
        logger.warning(f'Bot API call {method} skipped: TOKEN is not configured')
        return None

    connector = _get_connector()
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=client_timeout) as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if not data.get('ok'):
                    logger.debug(f'Bot API {method} returned error: {data.get("description")} (code {data.get("error_code")})')
                    return None
                return data.get('result')
    except Exception as e:
        logger.debug(f'Bot API {method} request failed: {e}')
        return None


def render_widget_html(title: Optional[str] = None,
                       feed_title: Optional[str] = None,
                       author: Optional[str] = None,
                       content_html: str = '',
                       link: Optional[str] = None,
                       tags: Optional[list[str]] = None) -> str:
    """
    Render clean, responsive HTML for Telegram Bot API 10.4 Native Widget.
    Enforces the <= 32KB limit required by Telegram.
    """
    meta_parts = []
    if feed_title:
        meta_parts.append(f'<b>📡 {html.escape(feed_title)}</b>')
    if author:
        meta_parts.append(f'<span>✍️ {html.escape(author)}</span>')

    meta_bar = f'<div class="widget-meta">{" · ".join(meta_parts)}</div>' if meta_parts else ''

    title_html = ''
    if title:
        escaped_title = html.escape(title)
        if link:
            title_html = f'<h2 class="widget-title"><a href="{html.escape(link)}" target="_blank">{escaped_title}</a></h2>'
        else:
            title_html = f'<h2 class="widget-title">{escaped_title}</h2>'

    footer_items = []
    if tags:
        tag_str = ' '.join(f'#{html.escape(t)}' for t in tags[:6])
        footer_items.append(f'<span class="widget-tags">{tag_str}</span>')
    if link:
        footer_items.append(f'<a class="widget-link" href="{html.escape(link)}" target="_blank">🔗 阅读全文</a>')

    footer_bar = f'<div class="widget-footer">{" · ".join(footer_items)}</div>' if footer_items else ''

    # Template with inline modern CSS suitable for dark/light themes
    css = (
        '<style>'
        ':root{color-scheme:light dark;}'
        'body{margin:0;padding:12px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;'
        'font-size:15px;line-height:1.6;color:var(--tg-theme-text-color,#222);background:var(--tg-theme-bg-color,#fff);}'
        'a{color:var(--tg-theme-link-color,#2481cc);text-decoration:none;}'
        'a:hover{text-decoration:underline;}'
        '.widget-card{border-radius:12px;box-sizing:border-box;}'
        '.widget-meta{font-size:12px;opacity:0.75;margin-bottom:6px;display:flex;flex-wrap:wrap;gap:8px;}'
        '.widget-title{font-size:18px;line-height:1.3;margin:0 0 10px 0;font-weight:700;}'
        '.widget-content{margin:8px 0;word-break:break-word;}'
        '.widget-content img{max-width:100%;height:auto;border-radius:8px;margin:6px 0;}'
        '.widget-content blockquote{border-left:3px solid var(--tg-theme-link-color,#2481cc);margin:8px 0;padding-left:10px;opacity:0.85;}'
        '.widget-footer{margin-top:14px;padding-top:8px;border-top:1px solid rgba(128,128,128,0.2);font-size:13px;display:flex;justify-content:space-between;align-items:center;}'
        '.widget-tags{opacity:0.7;font-size:12px;}'
        '</style>'
    )

    placeholder = '<!--__CONTENT_BODY__-->'
    base_frame = (
        f'<!DOCTYPE html><html><head><meta charset="utf-8">{css}</head>'
        f'<body><div class="widget-card">{meta_bar}{title_html}'
        f'<div class="widget-content">{placeholder}</div>'
        f'{footer_bar}</div></body></html>'
    )

    # Check size constraint: Telegram max widget HTML is 32KB (32768 bytes)
    max_payload_bytes = 30000  # safe margin below 32KB
    frame_empty = base_frame.replace(placeholder, '')
    frame_overhead = len(frame_empty.encode('utf-8'))
    available_content_bytes = max(100, max_payload_bytes - frame_overhead)

    content_bytes = content_html.encode('utf-8')
    if len(content_bytes) > available_content_bytes:
        truncated_content = content_bytes[:available_content_bytes].decode('utf-8', errors='ignore')
        # append truncation notice
        if link:
            truncated_content += f'<p><i>... (内容较长已在组件中截断，<a href="{html.escape(link)}">点击阅读全文</a>)</i></p>'
        else:
            truncated_content += '<p><i>... (内容较长已在组件中截断)</i></p>'
        final_html = base_frame.replace(placeholder, truncated_content)
    else:
        final_html = base_frame.replace(placeholder, content_html)

    # Telegram 10.4 constraint: max 32768 bytes UTF-8, and max 4096 bytes when compressed with zlib level 9
    while len(final_html.encode('utf-8')) > 30000 or len(zlib.compress(final_html.encode('utf-8'), level=9)) > 4000:
        available_content_bytes = int(available_content_bytes * 0.75)
        if available_content_bytes < 50:
            break
        truncated_content = content_bytes[:available_content_bytes].decode('utf-8', errors='ignore')
        if link:
            truncated_content += f'<p><i>... (内容较长已截断，<a href="{html.escape(link)}">阅读全文</a>)</i></p>'
        else:
            truncated_content += '<p><i>... (内容较长已截断)</i></p>'
        final_html = base_frame.replace(placeholder, truncated_content)

    return final_html


def render_help_widget_html(is_manager: bool = False, lang: Optional[str] = None) -> str:
    """
    Render clean Telegram Bot API 10.4 Native Widget for /help command.
    """
    css = (
        '<style>'
        ':root{color-scheme:light dark;}'
        'body{margin:0;padding:12px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-size:14px;line-height:1.5;color:var(--tg-theme-text-color,#222);background:var(--tg-theme-bg-color,#fff);}'
        '.card{border-radius:12px;}'
        '.title{font-size:16px;font-weight:700;color:var(--tg-theme-link-color,#2481cc);margin-bottom:4px;display:flex;align-items:center;gap:6px;}'
        '.sub{font-size:12px;opacity:0.7;margin-bottom:12px;}'
        '.sec-title{font-weight:600;font-size:13px;margin:10px 0 4px 0;opacity:0.85;border-bottom:1px solid rgba(128,128,128,0.2);padding-bottom:2px;}'
        '.item{padding:3px 0;font-size:13px;}'
        '.code{font-family:monospace;font-weight:bold;color:var(--tg-theme-link-color,#2481cc);background:rgba(36,129,204,0.08);padding:1px 4px;border-radius:4px;}'
        '.tip{margin-top:12px;padding:8px 10px;border-radius:8px;background:rgba(128,128,128,0.08);font-size:12px;line-height:1.4;}'
        '</style>'
    )

    manager_section = ''
    if is_manager:
        manager_section = (
            '<div class="sec-title">🛠 管理员命令</div>'
            '<div class="item"><span class="code">/set_option</span> 调整机器人全局系统参数</div>'
            '<div class="item"><span class="code">/user_info</span> 查看或修改用户信息</div>'
        )

    html_content = (
        f'<!DOCTYPE html><html><head><meta charset="utf-8">{css}</head><body><div class="card">'
        '<div class="title">🤖 RSStT · Telegram 10.4 原生 Widget</div>'
        '<div class="sub">关心你的阅读体验的 Telegram RSS 机器人</div>'
        '<div class="sec-title">📌 常用命令</div>'
        '<div class="item"><span class="code">/sub</span> 添加订阅</div>'
        '<div class="item"><span class="code">/unsub</span> 退订指定订阅</div>'
        '<div class="item"><span class="code">/list</span> 查看订阅列表</div>'
        '<div class="item"><span class="code">/set</span> 调整单个订阅个性化设置</div>'
        '<div class="item"><span class="code">/set_default</span> 设置全局默认偏好</div>'
        '<div class="sec-title">⚡ 10.4 专属测试命令</div>'
        '<div class="item"><span class="code">/test &lt;url&gt;</span> 测试抓取并以 10.4 Widget 发送文章</div>'
        f'{manager_section}'
        '<div class="tip">💡 <b>频道使用提示：</b>在频道中请将 Bot 设为管理员，并在私聊发送 <code>/sub @频道名 &lt;RSS地址&gt;</code> 绑定订阅。</div>'
        '</div></body></html>'
    )
    return html_content


async def send_widget(chat_id: Union[int, str],
                      html_content: str,
                      reply_to_message_id: Optional[int] = None) -> Optional[dict]:
    """
    Send an interactive HTML Widget message using Telegram Bot API 10.4 sendWidget.
    Note: In Telegram production environment, sendWidget is supported for private chats.
    """
    payload = {
        'chat_id': chat_id,
        'html': html_content,
    }
    if reply_to_message_id:
        payload['reply_to_message_id'] = reply_to_message_id

    return await call_bot_api('sendWidget', payload)


async def send_ephemeral_message(chat_id: Union[int, str],
                                 text: str,
                                 callback_query_id: Union[int, str],
                                 parse_mode: str = 'HTML',
                                 reply_markup: Optional[dict] = None) -> Optional[dict]:
    """
    Send an Ephemeral Message (visible only to the user who clicked the callback button)
    using Telegram Bot API 10.4 ephemeral_message_parameters.
    """
    try:
        cb_id_val = int(callback_query_id)
    except (ValueError, TypeError):
        cb_id_val = str(callback_query_id)

    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode,
        'ephemeral_message_parameters': {
            'callback_query_id': cb_id_val
        }
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup

    return await call_bot_api('sendMessage', payload)


async def answer_widget_query(widget_query_id: str,
                              text: Optional[str] = None,
                              url: Optional[str] = None) -> Optional[dict]:
    """
    Answer an incoming widget query from Bot API 10.4 WidgetQuery.
    """
    payload: dict[str, Any] = {'widget_query_id': widget_query_id}
    if text:
        payload['text'] = text
    if url:
        payload['url'] = url
    return await call_bot_api('answerWidgetQuery', payload)
