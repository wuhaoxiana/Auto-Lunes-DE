#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, re, sys, time, json, pickle, platform, subprocess, logging
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional

from seleniumbase import SB
from seleniumbase.common.exceptions import TimeoutException

# ================== 配置 ==================
LUNES_LOGIN_URL = "https://betadash.lunes.host/login"
LUNES_BASE = "https://betadash.lunes.host"

SERVER_ID = os.environ.get("LUNES_SERVER_ID") or "89950"
SERVER_URL = f"{LUNES_BASE}/servers/{SERVER_ID}"

OUTPUT_DIR = Path("output/screenshots")
COOKIE_FILE = Path("session_cookies.pkl")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ================== 日志 ==================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("lunes-keep")


# ================== 辅助函数 ==================
def is_linux() -> bool:
    return platform.system().lower() == "linux"


def mask_url(url: str) -> str:
    return re.sub(r'/servers/\d+', '/servers/***', url)


def mask_email(email: str) -> str:
    if '@' not in email:
        return email[:1] + "***"
    local, domain = email.split('@', 1)
    masked_local = local[:1] + "***" if local else "***"
    if '.' in domain:
        parts = domain.split('.')
        first_char = domain[0]
        masked_domain = f"{first_char}***.{parts[-1]}"
    else:
        masked_domain = domain[:1] + "***"
    return f"{masked_local}@{masked_domain}"


def setup_display():
    if is_linux() and not os.environ.get("DISPLAY"):
        try:
            from pyvirtualdisplay import Display
            display = Display(visible=False, size=(1920, 1080))
            display.start()
            os.environ["DISPLAY"] = display.new_display_var
            logger.info("虚拟显示已启动")
            return display
        except Exception as e:
            logger.error(f"虚拟显示启动失败: {e}")
            sys.exit(1)
    return None


def screenshot_path(name: str) -> str:
    return str(OUTPUT_DIR / f"{datetime.now().strftime('%H%M%S')}-{name}.png")


def safe_screenshot(sb, path: str):
    try:
        sb.save_screenshot(path)
        logger.info(f"截图 -> {Path(path).name}")
    except Exception as e:
        logger.warning(f"截图失败: {e}")


def notify_telegram(email: str, ok: bool, msg: str = "", screenshot_file: str = None):
    try:
        token = os.environ.get("TG_BOT_TOKEN")
        chat_id = os.environ.get("TG_CHAT_ID")
        if not token or not chat_id:
            return

        status = "Lunes 保活成功" if ok else "Lunes 保活失败"
        lines = [
            f"{'✅' if ok else '❌'} {status}",
            "",
            f"账号：{mask_email(email)}",
        ]
        if msg:
            lines.append(f"信息：{msg}")
        lines.append(f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"服务器 ID: {SERVER_ID}")
        lines.append("")
        lines.append("Lunes Host Auto Keep Alive")
        text = "\n".join(lines)

        if screenshot_file and Path(screenshot_file).exists():
            with open(screenshot_file, "rb") as f:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    data={"chat_id": chat_id, "caption": text},
                    files={"photo": f},
                    timeout=60
                )
        else:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                timeout=30
            )
    except Exception as e:
        logger.warning(f"Telegram 通知失败: {e}")


def check_and_exit_on_rate_limit(sb, email: str) -> None:
    try:
        page_source = sb.get_page_source()
        if "Too Many Requests" in page_source or "20 per 1 hour" in page_source:
            logger.error("检测到速率限制: Too Many Requests / 20 per 1 hour")
            sp = screenshot_path("rate-limit")
            safe_screenshot(sb, sp)
            notify_telegram(email=email, ok=False,
                            msg="IP 已被限制（Too Many Requests, 20/h），脚本已停止",
                            screenshot_file=sp)
            sys.exit(1)
    except Exception:
        pass


def parse_single_account() -> tuple[str, str]:
    raw = os.environ.get("LUNES", "").strip()
    if not raw:
        logger.error("未设置环境变量 LUNES，请设置 LUNES=邮箱-----密码")
        sys.exit(1)

    try:
        parts = raw.split("-----")
        if len(parts) >= 2:
            email = parts[0].strip()
            password = parts[1].strip()
            if email and password:
                logger.info(f"读取到账号: {mask_email(email)}")
                return email, password
        logger.error("LUNES 中邮箱或密码为空")
        sys.exit(1)
    except Exception as e:
        logger.error(f"解析 LUNES 失败: {e}")
        sys.exit(1)


# ================== Cookie 持久化 ==================
def save_cookies_to_file(driver) -> bool:
    try:
        cookies = driver.get_cookies()
        with open(COOKIE_FILE, "wb") as f:
            pickle.dump(cookies, f)
        logger.info(f"Cookie 已保存 ({len(cookies)} 个)")
        return True
    except Exception as e:
        logger.warning(f"保存 Cookie 失败: {e}")
        return False


def load_cookies_from_file(driver) -> bool:
    cookies = None
    pkl_path = COOKIE_FILE
    json_path = COOKIE_FILE.with_suffix(".json")

    if pkl_path.exists():
        try:
            with open(pkl_path, "rb") as f:
                cookies = pickle.load(f)
            logger.info("从 pickle 读取 Cookie")
        except Exception as e:
            logger.warning(f"读 pickle 失败: {e}")

    if cookies is None and json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            logger.info("从 JSON 读取 Cookie")
        except Exception as e:
            logger.warning(f"读 JSON 失败: {e}")

    if cookies is None:
        logger.info("Cookie 文件不存在")
        return False

    now = time.time()
    valid = [c for c in cookies if c.get('expiry', now) > now]
    expired = len(cookies) - len(valid)
    if not valid:
        logger.warning("所有 Cookie 已过期")
        return False
    if expired > 0:
        logger.info(f"{expired} 个 Cookie 已过期，已过滤")

    logger.info(f"加载 {len(valid)}/{len(cookies)} 个有效 Cookie...")
    for _ in range(3):
        try:
            driver.get(LUNES_BASE)
            time.sleep(2)
            break
        except:
            time.sleep(1)

    added = 0
    for cookie in valid:
        try:
            c = {k: v for k, v in cookie.items()
                 if k in ['name', 'value', 'domain', 'path', 'secure', 'httpOnly', 'sameSite', 'expiry']}
            driver.add_cookie(c)
            added += 1
        except Exception as e:
            logger.warning(f"添加 Cookie ({cookie.get('name')}) 失败: {e}")

    logger.info(f"Cookie 加载完成 ({added}/{len(valid)})")
    return added > 0


def try_cookie_login(sb) -> Optional[str]:
    logger.info("尝试用 Cookie 恢复会话...")
    if not load_cookies_from_file(sb.driver):
        return None

    time.sleep(1)
    sb.driver.get(LUNES_BASE)
    time.sleep(5)

    current_url = sb.driver.current_url
    logger.info(f"Cookie 会话 URL: {mask_url(current_url)}")

    if "/login" in current_url:
        logger.warning("Cookie 已失效（跳回登录页）")
        return None
    if "challenge" in current_url:
        logger.warning("Cookie 会话触发了 CF 挑战")
        return None

    logger.info("Cookie 会话有效！已跳过登录")
    return current_url


# ================== 登录流程 ==================
def clear_browser_state(sb):
    try:
        sb.execute_script("localStorage.clear(); sessionStorage.clear();")
    except:
        pass
    try:
        sb.delete_all_cookies()
    except:
        pass
    logger.info("浏览器状态已清理")


def handle_initial_page(sb, email: str) -> Optional[str]:
    clear_browser_state(sb)

    logger.info("访问登录页...")
    sb.uc_open_with_reconnect(LUNES_LOGIN_URL, reconnect_time=8)
    time.sleep(4)
    check_and_exit_on_rate_limit(sb, email)

    safe_screenshot(sb, screenshot_path("01-initial"))
    current_url = sb.get_current_url()
    logger.info(f"当前URL: {mask_url(current_url)}")

    if "/login" not in current_url and current_url != LUNES_LOGIN_URL:
        logger.info("页面未到达登录页，尝试强制导航...")
        clear_browser_state(sb)
        sb.uc_open_with_reconnect(LUNES_LOGIN_URL, reconnect_time=8)
        time.sleep(4)
        check_and_exit_on_rate_limit(sb, email)

    logger.info("等待 Cloudflare 验证通过并加载登录表单...")
    for i in range(30):
        check_and_exit_on_rate_limit(sb, email)
        try:
            sb.wait_for_element_visible('input#email', timeout=2)
            logger.info(f"登录表单已加载（{i + 1}s）")
            return "need_login"
        except TimeoutException:
            pass
        time.sleep(1)

    safe_screenshot(sb, screenshot_path("02-no-form"))
    logger.error("未找到登录表单（CF 验证可能未通过）")
    return None


def fill_and_submit(sb, email: str, password: str) -> bool:
    logger.info("填写登录信息...")
    try:
        sb.clear('input#email')
    except:
        pass
    sb.type('input#email', email)
    time.sleep(0.5)

    try:
        sb.clear('input#password')
    except:
        pass
    sb.type('input#password', password)
    time.sleep(0.5)

    safe_screenshot(sb, screenshot_path("03-form-filled"))

    logger.info("提交登录...")
    submitted = False
    for selector in ['button.submit-btn', 'button[type="submit"]']:
        try:
            sb.click(selector)
            submitted = True
            logger.info(f"通过 {selector} 提交")
            break
        except:
            continue

    if not submitted:
        try:
            sb.execute_script('document.querySelector("form").submit()')
            submitted = True
            logger.info("通过 JS 提交")
        except:
            logger.error("所有提交方式都失败")
            return False

    logger.info("等待登录结果...")
    time.sleep(6)
    check_and_exit_on_rate_limit(sb, email)

    current_url = sb.get_current_url()
    logger.info(f"登录后URL: {mask_url(current_url)}")

    if "/login" in current_url:
        try:
            error_msg = sb.execute_script(
                "var el = document.querySelector('.flash-message, .error-message, .alert');"
                "return el ? el.innerText.trim() : '';"
            )
            if error_msg:
                logger.error(f"登录错误提示: {error_msg}")
        except:
            pass
        safe_screenshot(sb, screenshot_path("05-login-failed"))
        logger.error("登录失败 - 仍在登录页")
        return False

    logger.info("登录成功！")
    return True


def navigate_to_server(sb, email: str) -> tuple[bool, str, Optional[str]]:
    time.sleep(3)
    sp = screenshot_path("06-dashboard")
    safe_screenshot(sb, sp)
    check_and_exit_on_rate_limit(sb, email)

    current_url = sb.get_current_url()
    logger.info(f"当前URL: {mask_url(current_url)}")

    # 直接跳转到服务器详情页
    logger.info(f"跳转到服务器: {SERVER_URL}")
    sb.driver.get(SERVER_URL)
    time.sleep(5)

    current_url = sb.get_current_url()
    logger.info(f"详情页URL: {mask_url(current_url)}")

    if "/servers/" in current_url:
        logger.info("成功进入服务器详情页")
        return True, SERVER_ID, sp

    # 降级：尝试找服务器卡片点击
    for sel in ['a.server-card', 'a[href*="/servers/"]', '.server-card']:
        try:
            sb.wait_for_element_visible(sel, timeout=5)
            sb.click(sel)
            time.sleep(5)
            current_url = sb.get_current_url()
            if "/servers/" in current_url:
                logger.info("通过卡片点击进入服务器详情页")
                return True, SERVER_ID, sp
        except:
            continue

    safe_screenshot(sb, screenshot_path("07-no-server"))
    try:
        body = sb.execute_script("return document.body.innerText.trim().toLowerCase()")
        if any(hint in body for hint in ["no server", "no servers", "没有服务器", "create a server"]):
            logger.warning("该账号下没有服务器")
            return False, "NO_SERVER", sp
    except:
        pass
    return False, "NAV_ERROR", sp


# ================== 从 Secret 生成 Cookie 文件 ==================
def generate_cookie_from_secret():
    session_val = os.environ.get("SESSION_COOKIE", "").strip()
    if not session_val:
        logger.info("SESSION_COOKIE 未设置，将尝试完整登录")
        return

    cookies = [{
        "name": "session",
        "value": session_val,
        "domain": "betadash.lunes.host",
        "path": "/",
        "secure": True,
        "httpOnly": True,
        "sameSite": "Lax",
        "expiry": 1900000000
    }]

    with open("session_cookies.pkl", "wb") as f:
        pickle.dump(cookies, f)

    with open("session_cookies.json", "w") as f:
        json.dump(cookies, f)

    logger.info(f"Cookie 文件已从 Secret 生成: {len(cookies)} 个 Cookie")


# ================== 主登录函数 ==================
def betadash_login(email: str, password: str, proxy: Optional[str] = None, max_retries: int = 1) -> dict:
    result = {"success": False, "message": "", "screenshot": None}

    logger.info("=" * 50)
    logger.info(f"Lunes Host 保活 | 邮箱: {mask_email(email)}")
    logger.info(f"服务器: {SERVER_ID}")
    logger.info("=" * 50)

    for attempt in range(max_retries):
        if attempt > 0:
            logger.warning("已尝试过一次，不再重试")
            break

        try:
            sb_kwargs = dict(
                uc=True, test=True, locale="en",
                headed=not is_linux(), user_data_dir=None,
                chromium_arg="--disable-blink-features=AutomationControlled",
            )
            if proxy:
                sb_kwargs["proxy"] = proxy

            with SB(**sb_kwargs) as sb:
                # 第一步：优先用 Cookie 恢复会话
                cookie_url = try_cookie_login(sb)
                if cookie_url:
                    logger.info("Cookie 会话有效，跳过登录流程")
                    sb.driver.get(SERVER_URL)
                    time.sleep(5)

                    if "/servers/" in sb.driver.current_url:
                        result.update(success=True, message=f"服务器: {SERVER_ID} (Cookie)",
                                      screenshot=screenshot_path("cookie-direct"))
                        logger.info("保活成功！")
                        return result

                    nav_ok, sid, sp = navigate_to_server(sb, email)
                    if nav_ok:
                        result.update(success=True, message=f"服务器: {sid} (Cookie+导航)")
                        return result

                # 第二步：Cookie 无效，走完整登录
                logger.warning("Cookie 无效，走完整登录流程")
                clear_browser_state(sb)

                init_status = handle_initial_page(sb, email)
                if init_status is None:
                    result["message"] = "Cloudflare 绕过失败或登录表单未找到"
                    result["screenshot"] = screenshot_path("02-cf-failed")
                    break

                if init_status == "need_login":
                    login_ok = fill_and_submit(sb, email, password)
                    if not login_ok:
                        result["message"] = "登录失败（凭据错误或提交异常）"
                        result["screenshot"] = screenshot_path("05-login-failed")
                        break
                    save_cookies_to_file(sb.driver)

                nav_ok, server_id, sp = navigate_to_server(sb, email)
                if nav_ok:
                    result.update(success=True, message=f"服务器: {server_id} (新登录)", screenshot=sp)
                    return result

                if server_id == "NO_SERVER":
                    result.update(success=True, message="登录成功，但账号下无服务器", screenshot=sp)
                    return result

                result.update(message=f"导航失败: {server_id}", screenshot=sp)
                return result

        except Exception as e:
            logger.exception(f"执行异常: {e}")
            result["message"] = str(e)

    return result


# ================== 主程序 ==================
def main():
    email, password = parse_single_account()
    proxy = os.environ.get("PROXY_SERVER")
    display = setup_display()

    # 从 Secret 预生成 Cookie 文件
    generate_cookie_from_secret()

    try:
        result = betadash_login(email, password, proxy, max_retries=1)

        notify_telegram(
            email=email,
            ok=result["success"],
            msg=result["message"],
            screenshot_file=result["screenshot"],
        )

        if result["success"]:
            logger.info("保活流程完成")
            sys.exit(0)
        else:
            logger.error("保活失败")
            sys.exit(1)

    finally:
        if display:
            display.stop()


if __name__ == "__main__":
    main()
