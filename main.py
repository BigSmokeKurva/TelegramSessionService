import asyncio
import json
import os
from random import choice
from urllib.parse import unquote

import python_socks
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from telethon import TelegramClient, functions
from telethon.errors import PhoneNumberInvalidError
from telethon.tl.functions.account import UpdateNotifySettingsRequest
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.types import InputPeerNotifySettings, NotificationSoundNone, InputBotAppShortName

from openteleMain.src.api import UseCurrentSession
from openteleMain.src.exception import TDesktopUnauthorized, OpenTeleException
from openteleMain.src.td import TDesktop


class ApiJsonError(Exception):
    pass


app = FastAPI()

SYSTEM_VERSIONS = ["Windows 10", "Windows 11"]
APP_VERSIONS = [
    "5.2.3, ""5.2.2",
    "5.2.0", "5.1.8", "5.1.7", "5.1.6", "5.1.5", "5.1.4", "5.1.3", "5.1.2", "5.1.1", "5.1.0",
    "5.0.0", "4.16.10", "4.16.9", "4.16.8", "4.16.7", "4.16.6", "4.16.5", "4.16.4", "4.16.3",
    "4.16.2", "4.16.1", "4.16.0"
]
DEFAULT_MUTE_SETTINGS = InputPeerNotifySettings(
    silent=True,
    sound=NotificationSoundNone()
)


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
        api_json["system_version"] = ""

    if "app_version" not in api_json:
        raise ApiJsonError()

    if "system_lang_code" not in api_json:
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


async def _get_client(data, proxy_dict):
    if data['sessionType'] == 'tdata':
        tdata = TDesktop(os.path.join(data['pathDirectory'], data['fileName']))
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
        data["fileName"] = str(data["id"]) + ".session"
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
        client = TelegramClient(
            session=os.path.join(data['pathDirectory'], data['fileName']),
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

    return client


async def _get_blum(client, data):
    chat = await client.get_input_entity('BlumCryptoBot')
    web_view = await client(functions.messages.RequestAppWebViewRequest(
        peer='me',
        app=InputBotAppShortName(bot_id=chat, short_name="start"),
        platform='android',
        write_allowed=True,
    )) if data["referralCode"] is not None else await client(functions.messages.RequestAppWebViewRequest(
        peer='me',
        app=InputBotAppShortName(bot_id=chat, short_name="start"),
        platform='android',
        write_allowed=True,
        start_param=data["referralCode"]
    ))

    auth_url = web_view.url
    tg_web_app_data = unquote(
        string=unquote(string=auth_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0]))
    return tg_web_app_data


async def _get_iceberg(client, data):
    try:
        chat = await client.get_input_entity('IcebergAppBot')
        messages = await client.get_messages(chat, limit=1)
        if not len(messages):
            if data["referralCode"] is None or data["referralCode"] == "":
                await client.send_message('IcebergAppBot', '/start')
            else:
                await client.send_message('IcebergAppBot', '/start ' + data["referralCode"])
    except:
        pass
    web_view = await client(functions.messages.RequestWebViewRequest(
        peer='IcebergAppBot',
        bot='IcebergAppBot',
        platform='android',
        from_bot_menu=True,
        url='https://0xiceberg.com/webapp/',
    ))
    auth_url = web_view.url
    tg_web_app_data = unquote(
        string=unquote(string=auth_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0]))
    return tg_web_app_data


async def _get_tapswap(client, data):
    try:
        chat = await client.get_input_entity('tapswap_bot')
        messages = await client.get_messages(chat, limit=1)
        if not len(messages):
            if data["referralCode"] is None or data["referralCode"] == "":
                await client.send_message('tapswap_bot', '/start')
            else:
                await client.send_message('tapswap_bot', '/start ' + data["referralCode"])
    except:
        pass
    web_view = await client(functions.messages.RequestWebViewRequest(
        peer='tapswap_bot',
        bot='tapswap_bot',
        platform='android',
        from_bot_menu=True,
        url='https://app.tapswap.club/',
    ))
    auth_url = web_view.url
    tg_web_app_data = unquote(
        string=unquote(string=auth_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0]))
    return tg_web_app_data


async def _get_dogs(client, data):
    chat = await client.get_input_entity('dogshouse_bot')
    web_view = await client(functions.messages.RequestAppWebViewRequest(
        peer='me',
        app=InputBotAppShortName(bot_id=chat, short_name="start"),
        platform='android',
        write_allowed=True,
    )) if data["referralCode"] is not None else await client(functions.messages.RequestAppWebViewRequest(
        peer='me',
        app=InputBotAppShortName(bot_id=chat, short_name="start"),
        platform='android',
        write_allowed=True,
        start_param=data["referralCode"]
    ))
    auth_url = web_view.url
    tg_web_app_data = unquote(
        string=unquote(string=auth_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0]))
    return tg_web_app_data


async def _get_onewin(client, data):
    chat = await client.get_input_entity('token1win_bot')
    web_view = await client(functions.messages.RequestAppWebViewRequest(
        peer='me',
        app=InputBotAppShortName(bot_id=chat, short_name="start"),
        platform='android',
        write_allowed=True,
        start_param=data["referralCode"]
    )) if data["referralCode"] is not None else await client(functions.messages.RequestAppWebViewRequest(
        peer='me',
        app=InputBotAppShortName(bot_id=chat, short_name="start"),
        platform='android',
        write_allowed=True,
    ))
    auth_url = web_view.url
    tg_web_app_data = unquote(
        string=unquote(string=auth_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0]))
    return tg_web_app_data


async def _get_tg_web_app_data(data, proxy_dict):
    client = None
    try:
        client = await _get_client(data, proxy_dict)
        await client.start(phone='0')
        me = await client.get_me()

        if data["service"] == "blum":
            tg_web_app_data = await _get_blum(client, data)
        elif data["service"] == "iceberg":
            tg_web_app_data = await _get_iceberg(client, data)
        elif data["service"] == "dogs":
            tg_web_app_data = await _get_dogs(client, data)
        elif data["service"] == "tapswap":
            tg_web_app_data = await _get_tapswap(client, data)
        elif data["service"] == "onewin":
            tg_web_app_data = await _get_onewin(client, data)
        else:
            tg_web_app_data = None

        await client.disconnect()
        return JSONResponse(
            {
                "status": "success",
                "tgWebAppData": tg_web_app_data,
                "number": me.phone,
                "fileName": data["fileName"],
                "apiJson": json.dumps(data['apiJson']),
            })
    except Exception as e:
        try:
            if client is not None:
                await client.disconnect()
                client = None
        except Exception as ex:
            pass
        print(str(e))
        with open("error.txt", "a") as f:
            f.write(str(e) + "\n")
        raise e


@app.post("/api/getTgWebAppData")
async def get_tg_web_app_data(request: Request):
    data = await request.json()

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
    try:
        return await asyncio.wait_for(_get_tg_web_app_data(data, proxy_dict), timeout=20)
    except ConnectionError:
        return JSONResponse({"status": "proxy_error"})
    except asyncio.TimeoutError:
        return JSONResponse({"status": "proxy_error"})
    except (TDesktopUnauthorized, OpenTeleException, PhoneNumberInvalidError, ApiJsonError):
        return JSONResponse({"status": "session_invalid"})
    except Exception as e:
        return JSONResponse({"status": "session_invalid"})


@app.post("/api/joinChannels")
async def join_channels(request: Request):
    client = None
    try:
        try:
            data = await request.json()
            if data['apiJson'] is not None:
                data['apiJson'] = proccess_api_json(json.loads(data['apiJson']))
            split_proxy = data['proxy'].split(':')
            proxy_dict = {
                "proxy_type": python_socks.ProxyType.SOCKS5 if split_proxy[
                                                                   0] == 'socks5' else python_socks.ProxyType.HTTP,
                "addr": split_proxy[1],
                "port": int(split_proxy[2]),
                "username": split_proxy[3],
                "password": split_proxy[4],
                'rdns': True
            }
            client = await _get_client(data, proxy_dict)
            await client.start(phone='0')
            me = await client.get_me()
            for channel in data['channels']:
                channel = await client.get_entity(channel)
                try:
                    await client(GetParticipantRequest(channel, me.id))
                except:
                    await client(functions.channels.JoinChannelRequest(channel))
                    await client(UpdateNotifySettingsRequest(
                        peer=channel,
                        settings=DEFAULT_MUTE_SETTINGS
                    ))
                    await client.edit_folder(channel, 1)
            await client.disconnect()
        except Exception as e:
            try:
                if client is not None:
                    await client.disconnect()
                    client = None
            except Exception as ex:
                pass
            print(str(e))
            with open("error.txt", "a") as f:
                f.write(str(e) + "\n")
            raise e
        return JSONResponse({"status": "success"})
    except ConnectionError:
        return JSONResponse({"status": "proxy_error"})
    except asyncio.TimeoutError:
        return JSONResponse({"status": "proxy_error"})
    except (TDesktopUnauthorized, OpenTeleException, PhoneNumberInvalidError, ApiJsonError):
        return JSONResponse({"status": "session_invalid"})
    except Exception as e:
        return JSONResponse({"status": "session_invalid"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=5000)
