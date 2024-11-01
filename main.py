import argparse
import asyncio
import json
import logging
import os
import random
import re
import string
from random import choice
from urllib.parse import unquote

import python_socks
from PyQt5.uic.Compiler.qobjectcreator import logger
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from telethon import TelegramClient, functions
from telethon.errors import PhoneNumberInvalidError, ApiIdPublishedFloodError, ApiIdInvalidError
from telethon.tl.functions.account import UpdateNotifySettingsRequest
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import InputPeerNotifySettings, NotificationSoundNone, InputBotAppShortName, User
from unidecode import unidecode

from openteleMain.src.api import UseCurrentSession
from openteleMain.src.exception import OpenTeleException, TDesktopUnauthorized
from openteleMain.src.td import TDesktop


class ApiJsonError(Exception):
    pass


class ProxyError(Exception):
    pass


class SessionInvalidError(Exception):
    pass


class UnknownError(Exception):
    status_code: int
    detail: str

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


app = FastAPI(debug=False)

logging.getLogger('telethon').setLevel(logging.ERROR)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SYSTEM_VERSIONS = ["Windows 10", "Windows 11"]
APP_VERSIONS = [
    "5.6.2", "5.6.1", "5.6.0", "5.5.5", "5.5.4", "5.5.2", "5.5.1", "5.5.0",
    "5.3.1", "5.3.0", "5.2.3", "5.2.2"
]
DEFAULT_MUTE_SETTINGS = InputPeerNotifySettings(
    silent=True,
    sound=NotificationSoundNone()
)


@app.exception_handler(Exception)
async def handle_exceptions(request: Request, e):
    string_exception = str(e)
    # proxy error
    if isinstance(e, ConnectionError) or "ConnectionError" in string_exception:
        return proxy_error_handler(ProxyError("Failed to connect to proxy"), request)
    elif isinstance(e, asyncio.TimeoutError):
        return proxy_error_handler(ProxyError("Proxy connection timed out"), request)
    elif "The authorization key (session file) was used under two" in string_exception:
        return proxy_error_handler(ProxyError("Session file was used under two different keys"), request)
    # session error
    elif isinstance(e, PhoneNumberInvalidError) or "The phone number is invalid" in string_exception:
        return session_invalid_error_handler(SessionInvalidError(string_exception), request)
    elif isinstance(
            e, SessionInvalidError) or "SessionInvalidError" in string_exception:
        return session_invalid_error_handler(SessionInvalidError(string_exception), request)
    elif isinstance(e,
                    OpenTeleException) or "OpenTeleException" in string_exception:
        return session_invalid_error_handler(SessionInvalidError(string_exception), request)
    elif isinstance(e, ApiJsonError):
        return session_invalid_error_handler(SessionInvalidError(string_exception), request)

    elif isinstance(e,
                    TDesktopUnauthorized) or "TDesktopUnauthorized" in string_exception:
        return session_invalid_error_handler(SessionInvalidError(string_exception), request)
    elif isinstance(e,
                    ApiIdPublishedFloodError) or "This API id w" in string_exception:
        return session_invalid_error_handler(SessionInvalidError(string_exception), request)
    elif isinstance(e,
                    ApiIdInvalidError):
        return session_invalid_error_handler(SessionInvalidError(string_exception), request)
    elif "bytes read on a total" in string_exception:
        return session_invalid_error_handler(SessionInvalidError(string_exception), request)
    elif "(caused by SendCodeRequest)" in string_exception:
        return session_invalid_error_handler(SessionInvalidError(string_exception), request)
    elif "(caused by UpdateUsernameRequest)" in string_exception:
        return session_invalid_error_handler(SessionInvalidError(string_exception), request)
    elif "(caused by RequestWebViewRequest)" in string_exception:
        return session_invalid_error_handler(SessionInvalidError(string_exception), request)
    elif "(caused by ResolveUsernameRequest)" in string_exception:
        return session_invalid_error_handler(SessionInvalidError(string_exception), request)
    # ignore
    elif "JoinChannelRequest" in string_exception:
        return JSONResponse(
            status_code=200,
            content={"status": "success"},
        )
    # other errors
    else:
        logger.error(f"Unexpected error: {string_exception}")
        return await unknown_exception_handler(UnknownError(status_code=200, detail=string_exception), request)


def proxy_error_handler(exc: ProxyError, request: Request):
    return JSONResponse(
        status_code=200,
        content={"status": "proxy_error", "detail": str(exc), "data": get_body_as_string(request)},
    )


def session_invalid_error_handler(exc: SessionInvalidError, request: Request):
    return JSONResponse(
        status_code=200,
        content={"status": "session_invalid", "detail": str(exc), "data": get_body_as_string(request)},
    )


def unknown_exception_handler(exc: UnknownError, request: Request):
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "unknown_error", "detail": exc.detail, "data": get_body_as_string(request)},
    )


def get_body_as_string(request: Request) -> str:
    body = request.state.body
    return body.decode('utf-8')


async def handle_bot_start(client, bot_name, referral_code):
    chat = await client.get_input_entity(bot_name)
    messages = await client.get_messages(chat, limit=1)
    if not len(messages):
        if referral_code is None or referral_code == "":
            await client.send_message(bot_name, '/start')
        else:
            await client.send_message(bot_name, '/start ' + referral_code)


async def request_web_view(client, peer, bot, url, platform, referral_code=None):
    if referral_code is not None:
        web_view = await client(functions.messages.RequestWebViewRequest(
            peer=peer,
            bot=bot,
            platform=platform,
            from_bot_menu=True,
            url=url,
            start_param=referral_code
        ))
    else:
        web_view = await client(functions.messages.RequestWebViewRequest(
            peer=peer,
            bot=bot,
            platform=platform,
            from_bot_menu=True,
            url=url
        ))
    auth_url = web_view.url
    tg_web_app_data = unquote(
        string=unquote(string=auth_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0]))
    return tg_web_app_data, auth_url


async def request_app_web_view(client, bot_name, short_name, platform, referral_code=None):
    chat = await client.get_input_entity(bot_name)
    if referral_code is not None:
        web_view = await client(functions.messages.RequestAppWebViewRequest(
            peer='me',
            app=InputBotAppShortName(bot_id=chat, short_name=short_name),
            platform=platform,
            write_allowed=True,
            start_param=referral_code
        ))
    else:
        web_view = await client(functions.messages.RequestAppWebViewRequest(
            peer='me',
            app=InputBotAppShortName(bot_id=chat, short_name=short_name),
            platform=platform,
            write_allowed=True,
        ))
    auth_url = web_view.url
    tg_web_app_data = unquote(
        string=unquote(string=auth_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0]))
    return tg_web_app_data, auth_url


def process_data_and_proxy(data):
    if data['apiJson'] is None and data['sessionType'] == 'telethon':
        raise ApiJsonError()
    if data['apiJson'] is not None:
        data['apiJson'] = proccess_api_json(json.loads(data['apiJson']))
    split_proxy = data['proxy'].split(':')
    proxy_dict = {
        "proxy_type": python_socks.ProxyType.SOCKS5 if split_proxy[0] == 'socks5' else python_socks.ProxyType.HTTP,
        "addr": split_proxy[1],
        "port": int(split_proxy[2]),
        "username": split_proxy[3],
        "password": split_proxy[4],
        'rdns': True
    }
    return data, proxy_dict


def proccess_api_json(api_json):
    if "app_id" in api_json:
        api_json["api_id"] = api_json["app_id"]
    elif "api_id" in api_json:
        api_json["app_id"] = api_json["api_id"]
    else:
        raise ApiJsonError()

    if "app_hash" in api_json:
        api_json["api_hash"] = api_json["app_hash"]
    elif "api_hash" in api_json:
        api_json["app_hash"] = api_json["api_hash"]
    else:
        raise ApiJsonError()

    if "device" in api_json:
        api_json["device_model"] = api_json["device"]
    elif "device_model" in api_json:
        api_json["device"] = api_json["device_model"]
    else:
        raise ApiJsonError()

    if "system_version" not in api_json:
        api_json["system_version"] = get_system_version()

    if "app_version" not in api_json:
        raise ApiJsonError()

    if "system_lang_code" not in api_json and "lang_code" in api_json:
        api_json["system_lang_code"] = api_json["lang_code"]
    elif "system_lang_code" not in api_json and "system_lang_pack" in api_json:
        api_json["system_lang_code"] = api_json["system_lang_pack"]
    elif "system_lang_code" not in api_json:
        raise ApiJsonError()

    if "lang_code" not in api_json:
        api_json["lang_code"] = api_json["system_lang_code"]

    if "lang_pack" not in api_json:
        raise ApiJsonError()

    return api_json


def get_system_version():
    return choice(SYSTEM_VERSIONS)


def get_app_version():
    return choice(APP_VERSIONS) + " x64"


async def _get_client(data, proxy_dict) -> TelegramClient:
    if data['sessionType'] == 'tdata':
        tdata = TDesktop(os.path.join(data['pathDirectory'], data['id']))
        tdata.api.system_version = get_system_version()
        tdata.api.app_version = get_app_version()
        client = await tdata.ToTelethon(
            os.path.join(data['pathDirectory'], str(data['id']) + '.session'),
            api=tdata.api,
            proxy=proxy_dict,
            auto_reconnect=False,
            connection_retries=0,
            api_id=tdata.api.api_id,
            api_hash=tdata.api.api_hash,
            device_model=tdata.api.device_model,
            system_version=tdata.api.system_version,
            app_version=tdata.api.app_version,
            lang_code=tdata.api.lang_code,
            system_lang_code=tdata.api.system_lang_code,
            receive_updates=False,
            flag=UseCurrentSession
        )
        data["type"] = "telethon"
        data['apiJson'] = proccess_api_json({
            "api_id": tdata.api.api_id,
            "api_hash": tdata.api.api_hash,
            "device_model": tdata.api.device_model,
            "device": tdata.api.device_model,
            "system_version": tdata.api.system_version,
            "app_version": tdata.api.app_version,
            "system_lang_code": tdata.api.system_lang_code,
            "app_version": tdata.api.app_version,
            "lang_code": tdata.api.lang_code,
            "lang_pack": tdata.api.lang_pack,
            "pid": tdata.api.pid
        })
    else:
        for i in range(0, 4):
            try:
                client = TelegramClient(
                    session=os.path.join(data['pathDirectory'], data['id']) + ".session",
                    api_id=data['apiJson']['api_id'],
                    api_hash=data['apiJson']['api_hash'],
                    device_model=data['apiJson']['device_model'],
                    system_version=data['apiJson']['system_version'],
                    app_version=data['apiJson']['app_version'],
                    lang_code=data['apiJson']['lang_code'],
                    receive_updates=False,
                    proxy=proxy_dict,
                    auto_reconnect=False,
                    connection_retries=0
                )
                break
            except Exception as e:
                if i == 2:
                    raise e
                await asyncio.sleep(0.4)

    return client


async def set_username_if_not_exists(client, me=None):
    if me is None:
        me = await client.get_me()
    if me.username is None:
        try:
            username = generate_username(me.first_name, me.last_name)
            await client(functions.account.UpdateUsernameRequest(username))
            me = await client.get_me()
            if me.username is None:
                raise Exception("Username not set")
            return
        except:
            try:
                username = generate_username(me.first_name, me.last_name, numbersRange=[0, 99])
                await client(functions.account.UpdateUsernameRequest(username))
                me = await client.get_me()
                if me.username is None:
                    raise Exception("Username not set")
                return
            except:
                try:
                    username = generate_username()
                    await client(functions.account.UpdateUsernameRequest(username))
                    me = await client.get_me()
                    if me.username is None:
                        raise Exception("Username not set")
                    return
                except:
                    username = generate_username(numbersRange=[1000, 100000000])
                    await client(functions.account.UpdateUsernameRequest(username))
                    me = await client.get_me()
                    if me.username is None:
                        raise Exception("Username not set")
                    return


async def _get_blum(client, data):
    return await request_web_view(client, 'BlumCryptoBot', 'BlumCryptoBot', "https://telegram.blum.codes/",
                                  data.get("tgIdentification"),
                                  data.get("referralCode"))


async def _get_iceberg(client, data):
    await handle_bot_start(client, 'IcebergAppBot', data.get("referralCode"))
    return await request_web_view(client, 'IcebergAppBot', 'IcebergAppBot', 'https://0xiceberg.com/webapp/',
                                  data.get("tgIdentification"), None)


async def _get_tapswap(client, data):
    await handle_bot_start(client, 'tapswap_bot', data.get("referralCode"))
    return await request_web_view(client, 'tapswap_bot', 'tapswap_bot', 'https://app.tapswap.club/',
                                  data.get("tgIdentification"), None)


async def _get_banana(client, data):
    referral_code = None
    if data["referralCode"] is not None:
        referral_code = "referral=" + data["referralCode"]
    return await request_app_web_view(client, 'OfficialBananaBot', 'banana', data.get("tgIdentification"),
                                      referral_code)


async def _get_clayton(client, data):
    return await request_app_web_view(client, 'claytoncoinbot', 'game', data.get("tgIdentification"),
                                      data.get("referralCode"))


async def _get_cats(client, data):
    return await request_app_web_view(client, 'catsgang_bot', 'join', data.get("tgIdentification"),
                                      data.get("referralCode"))


async def _get_major(client, data):
    return await request_app_web_view(client, 'major', 'start', data.get("tgIdentification"), data.get("referralCode"))


async def _get_tonstation(client, data):
    return await request_app_web_view(client, 'tonstationgames_bot', 'app', data.get("tgIdentification"),
                                      data.get("referralCode"))


async def _get_horizon(client, data):
    return await request_app_web_view(client, 'HorizonLaunch_bot', 'HorizonLaunch', data.get("tgIdentification"),
                                      data.get("referralCode"))


async def _get_busers(client, data):
    return await request_app_web_view(client, 'b_usersbot', 'join', data.get("tgIdentification"),
                                      data.get("referralCode"))


async def _get_catsdogs(client, data):
    return await request_app_web_view(client, 'catsdogs_game_bot', 'join', data.get("tgIdentification"),
                                      data.get("referralCode"))


async def _get_notpixel(client, data):
    return await request_app_web_view(client, 'notpixel', 'app', data.get("tgIdentification"),
                                      data.get("referralCode"))


async def _get_notgames(client, data):
    return await request_app_web_view(client, 'notgames_bot', 'squads', data.get("tgIdentification"),
                                      data.get("referralCode"))


async def _get_paws(client, data):
    return await request_app_web_view(client, 'PAWSOG_bot', 'PAWS', data.get("tgIdentification"),
                                      data.get("referralCode"))


service_map = {
    "blum": _get_blum,
    "iceberg": _get_iceberg,
    "tapswap": _get_tapswap,
    "banana": _get_banana,
    "clayton": _get_clayton,
    "cats": _get_cats,
    "major": _get_major,
    "tonstation": _get_tonstation,
    "horizon": _get_horizon,
    "busers": _get_busers,
    "catsdogs": _get_catsdogs,
    "notpixel": _get_notpixel,
    "notgames": _get_notgames,
    "paws": _get_paws
}


async def _get_tg_web_app_data(client, data):
    # await client.start(phone='0')
    if not client.is_connected():
        await client.connect()
    if not await client.is_user_authorized():
        raise SessionInvalidError()
    if data["isUpload"] or data["otherInfo"]:
        me = await client.get_me()
    else:
        me = User(0)
    if data["isUpload"]:
        if data["sessionType"] == "telethon":
            tdata = await client.ToTDesktop(flag=UseCurrentSession)
            tdata.SaveTData(os.path.join(data['pathDirectory'], data["id"]))
        await set_username_if_not_exists(client, me)

    service_func = service_map.get(data["service"])
    if service_func:
        tg_web_app_data, auth_url = await service_func(client, data)
    else:
        raise UnknownError(400, f"Service '{data['service']}' not found in service map")

    return JSONResponse(
        {
            "status": "success",
            "tgWebAppData": tg_web_app_data,
            'authUrl': auth_url,
            "number": me.phone,
            "apiJson": json.dumps(data['apiJson']) if data["isUpload"] else None,
            'isPremium': me.premium,
            'username': me.username,
            'userId': me.id
        })


@app.post("/api/getTgWebAppData")
async def get_tg_web_app_data(request: Request):
    data = await request.json()
    data, proxy_dict = process_data_and_proxy(data)
    client = None
    try:
        client = await asyncio.wait_for(_get_client(data, proxy_dict), timeout=20)
        return await asyncio.wait_for(_get_tg_web_app_data(client, data), timeout=20)
    except Exception as e:
        raise e
    finally:
        if client:
            try:
                await client.disconnect()
            except:
                pass


async def _join_channels(client, data):
    if not client.is_connected():
        await client.connect()
    if not await client.is_user_authorized():
        raise SessionInvalidError()
    me = await client.get_me()
    for channel in data['channels']:
        if not channel:
            continue
        try:
            channel = await client.get_entity(channel)
            await client(GetParticipantRequest(channel, me.id))
        except:
            try:
                await client(functions.channels.JoinChannelRequest(channel))
                await client(UpdateNotifySettingsRequest(
                    peer=channel,
                    settings=DEFAULT_MUTE_SETTINGS
                ))
                await client.edit_folder(channel, 1)
            except Exception as e:
                pass
                # if "You have joined too many channels/supergroups" not in str(e):
                #    raise e
    return JSONResponse({"status": "success"})


@app.post("/api/joinChannels")
async def join_channels(request: Request):
    data = await request.json()
    data, proxy_dict = process_data_and_proxy(data)

    client = None
    try:
        client = await asyncio.wait_for(_get_client(data, proxy_dict), timeout=20)
        return await asyncio.wait_for(_join_channels(client, data), timeout=20)
    except Exception as e:
        raise e
    finally:
        if client:
            try:
                await client.disconnect()
            except:
                pass


async def _create_tdata(client, data):
    tdata = await client.ToTDesktop(flag=UseCurrentSession)
    tdata.save(data['pathDirectory'])
    return JSONResponse({"status": "success"})


@app.post("/api/createTData")
async def create_tdata(request: Request):
    data = await request.json()
    data, proxy_dict = process_data_and_proxy(data)

    client = None
    try:
        client = await asyncio.wait_for(_get_client(data, proxy_dict), timeout=20)
        return await asyncio.wait_for(_create_tdata(client, data), timeout=20)
    except Exception as e:
        raise e
    finally:
        if client:
            try:
                await client.disconnect()
            except:
                pass


async def _add_diamond(client):
    if not client.is_connected():
        await client.connect()
    if not await client.is_user_authorized():
        raise SessionInvalidError()
    me = await client.get_me()
    user = await client(GetFullUserRequest('me'))
    if (me.first_name and "💎" in me.first_name) or (me.last_name and "💎" in me.last_name):
        return JSONResponse({"status": "success"})
    if me.first_name:
        first_name = me.first_name + "💎"
        last_name = me.last_name
    else:
        first_name = me.first_name
        last_name = me.last_name + "💎"
    await client(functions.account.UpdateProfileRequest(first_name=first_name, last_name=last_name,
                                                        about=user.full_user.about))


@app.post("/api/addDiamond")
async def add_diamond(request: Request):
    data = await request.json()
    data, proxy_dict = process_data_and_proxy(data)

    client = None
    try:
        client = await asyncio.wait_for(_get_client(data, proxy_dict), timeout=20)
        return await asyncio.wait_for(_add_diamond(client), timeout=20)
    except Exception as e:
        raise e
    finally:
        if client:
            try:
                await client.disconnect()
            except:
                pass


async def _remove_diamond(client):
    if not client.is_connected():
        await client.connect()
    if not await client.is_user_authorized():
        raise SessionInvalidError()
    me = await client.get_me()
    user = await client(GetFullUserRequest('me'))
    if (me.first_name and "💎" not in me.first_name) or (me.last_name and "💎" not in me.last_name):
        return JSONResponse({"status": "success"})
    if me.first_name:
        first_name = me.first_name.replace("💎", "")
        last_name = me.last_name
    else:
        first_name = me.first_name
        last_name = me.last_name.replace("💎", "")
    await client(functions.account.UpdateProfileRequest(first_name=first_name, last_name=last_name,
                                                        about=user.full_user.about))


@app.post("/api/removeDiamond")
async def remove_diamond(request: Request):
    data = await request.json()
    data, proxy_dict = process_data_and_proxy(data)

    client = None
    try:
        client = await asyncio.wait_for(_get_client(data, proxy_dict), timeout=20)
        return await asyncio.wait_for(_remove_diamond(client), timeout=20)
    except Exception as e:
        raise e
    finally:
        if client:
            try:
                await client.disconnect()
            except:
                pass


async def _add_cat(client):
    if not client.is_connected():
        await client.connect()
    if not await client.is_user_authorized():
        raise SessionInvalidError()
    me = await client.get_me()
    user = await client(GetFullUserRequest('me'))
    if (me.first_name and "🐈‍⬛" in me.first_name) or (me.last_name and "🐈‍⬛" in me.last_name):
        return JSONResponse({"status": "success"})
    if me.first_name:
        first_name = me.first_name + "🐈‍⬛"
        last_name = me.last_name
    else:
        first_name = me.first_name
        last_name = me.last_name + "🐈‍⬛"
    await client(functions.account.UpdateProfileRequest(first_name=first_name, last_name=last_name,
                                                        about=user.full_user.about))


@app.post("/api/addCat")
async def add_cat(request: Request):
    data = await request.json()
    data, proxy_dict = process_data_and_proxy(data)

    client = None
    try:
        client = await asyncio.wait_for(_get_client(data, proxy_dict), timeout=20)
        return await asyncio.wait_for(_add_cat(client), timeout=20)
    except Exception as e:
        raise e
    finally:
        if client:
            try:
                await client.disconnect()
            except:
                pass


async def _remove_cat(client):
    if not client.is_connected():
        await client.connect()
    if not await client.is_user_authorized():
        raise SessionInvalidError()
    me = await client.get_me()
    user = await client(GetFullUserRequest('me'))
    if (me.first_name and "🐈‍⬛" not in me.first_name) or (me.last_name and "🐈‍⬛" not in me.last_name):
        return JSONResponse({"status": "success"})
    if me.first_name:
        first_name = me.first_name.replace("🐈‍⬛", "")
        last_name = me.last_name
    else:
        first_name = me.first_name
        last_name = me.last_name.replace("🐈‍⬛", "")
    await client(functions.account.UpdateProfileRequest(first_name=first_name, last_name=last_name,
                                                        about=user.full_user.about))


@app.post("/api/removeCat")
async def remove_cat(request: Request):
    data = await request.json()
    data, proxy_dict = process_data_and_proxy(data)

    client = None
    try:
        client = await asyncio.wait_for(_get_client(data, proxy_dict), timeout=20)
        return await asyncio.wait_for(_remove_cat(client), timeout=20)
    except Exception as e:
        raise e
    finally:
        if client:
            try:
                await client.disconnect()
            except:
                pass


async def _start_bot(client, data):
    if not client.is_connected():
        await client.connect()
    if not await client.is_user_authorized():
        raise SessionInvalidError()
    await handle_bot_start(client, data.get("bot"), data.get("referralCode"))


@app.post("/api/startBot")
async def start_bot(request: Request):
    data = await request.json()
    data, proxy_dict = process_data_and_proxy(data)

    client = None
    try:
        client = await asyncio.wait_for(_get_client(data, proxy_dict), timeout=20)
        return await asyncio.wait_for(_start_bot(client, data), timeout=20)
    except Exception as e:
        raise e
    finally:
        if client:
            try:
                await client.disconnect()
            except:
                pass


async def _add_pixel(client):
    if not client.is_connected():
        await client.connect()
    if not await client.is_user_authorized():
        raise SessionInvalidError()
    me = await client.get_me()
    user = await client(GetFullUserRequest('me'))
    if (me.first_name and "▪️" in me.first_name) or (me.last_name and "▪️" in me.last_name):
        return JSONResponse({"status": "success"})
    if me.first_name:
        first_name = me.first_name + "▪️"
        last_name = me.last_name
    else:
        first_name = me.first_name
        last_name = me.last_name + "▪️"
    await client(functions.account.UpdateProfileRequest(first_name=first_name, last_name=last_name,
                                                        about=user.full_user.about))


@app.post("/api/addPixel")
async def add_pixel(request: Request):
    data = await request.json()
    data, proxy_dict = process_data_and_proxy(data)

    client = None
    try:
        client = await asyncio.wait_for(_get_client(data, proxy_dict), timeout=20)
        return await asyncio.wait_for(_add_pixel(client), timeout=20)
    except Exception as e:
        raise e
    finally:
        if client:
            try:
                await client.disconnect()
            except:
                pass


async def _remove_pixel(client):
    if not client.is_connected():
        await client.connect()
    if not await client.is_user_authorized():
        raise SessionInvalidError()
    me = await client.get_me()
    user = await client(GetFullUserRequest('me'))
    if (me.first_name and "▪️" not in me.first_name) or (me.last_name and "▪️" not in me.last_name):
        return JSONResponse({"status": "success"})
    if me.first_name:
        first_name = me.first_name.replace("▪️", "")
        last_name = me.last_name
    else:
        first_name = me.first_name
        last_name = me.last_name.replace("▪️", "")
    await client(functions.account.UpdateProfileRequest(first_name=first_name, last_name=last_name,
                                                        about=user.full_user.about))


@app.post("/api/removePixel")
async def remove_pixel(request: Request):
    data = await request.json()
    data, proxy_dict = process_data_and_proxy(data)

    client = None
    try:
        client = await asyncio.wait_for(_get_client(data, proxy_dict), timeout=20)
        return await asyncio.wait_for(_remove_pixel(client), timeout=20)
    except Exception as e:
        raise e
    finally:
        if client:
            try:
                await client.disconnect()
            except:
                pass


@app.middleware("http")
async def capture_request_body(request: Request, call_next):
    request.state.body = await request.body()
    response = await call_next(request)
    return response


def generate_username(first_name=None, last_name=None, numbersRange=None):
    regex = r'^[a-zA-Z][\w\d]{3,30}[a-zA-Z\d]$'

    def create_base_username():
        base_username = "_".join(
            part.lower().replace(" ", "_") for part in (first_name, last_name) if part
        )
        if random.randint(0, 1):
            base_username = base_username.replace("_", "")

        if not base_username:
            base_username = ''.join(random.choices(string.ascii_lowercase, k=8))

        base_username = unidecode(base_username)

        return base_username

    base_username = create_base_username()

    username = re.sub(r'[^a-zA-Z0-9_]', '', base_username)[:28]

    suffix = ""
    if numbersRange is not None:
        if numbersRange[0] == -1:
            suffix = str(random.randint(1, 99))
        else:
            suffix = str(random.randint(numbersRange[0], numbersRange[1]))
    username = username + suffix

    username = username[:30]
    if re.match(regex, username):
        return username
    raise Exception("Bad username generated")


if __name__ == "__main__":
    import uvicorn

    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(message)s",
                "use_colors": True,
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {
                "level": "INFO",  # Уровень для общего логгера uvicorn
                "handlers": ["default"],
                "propagate": False,
            },
            "uvicorn.error": {
                "level": "CRITICAL",  # Отключаем логи уровня ERROR
                "handlers": ["default"],
                "propagate": False,
            },
            "uvicorn.access": {
                "level": "INFO",  # Логи доступа
                "handlers": ["default"],
                "propagate": False,
            },
        },
    }
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5000, help='Порт для запуска')
    args = parser.parse_args()
    logger.info(f"Started 127.0.0.1:{args.port}")
    # Запуск uvicorn с кастомной конфигурацией логирования
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_config=log_config)
