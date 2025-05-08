import os
import tomllib
import random, json
import secrets, hashlib

from flask import Flask, request, abort, jsonify

import google.generativeai as genai

from azure.ai.translation.text import TextTranslationClient
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError

from linebot import (
    LineBotApi, WebhookHandler
)

from linebot.exceptions import (
    InvalidSignatureError
)

from linebot.models import (
    MessageEvent,
    TextMessage,
    TextSendMessage,
    LocationSendMessage,
    VideoSendMessage,
    ImageSendMessage,
    StickerSendMessage
)


with open("config.toml", "rb") as f:
    cfg = tomllib.load(f)

genai.configure(api_key=cfg['gemini']['api_key'])
model = genai.GenerativeModel(
    model_name=cfg['gemini']['model_name'],
    system_instruction=cfg['gemini']['system_instruction']
)

def ask_gemini(user_input):
    try:
        response = model.generate_content(user_input)
        return response.text.strip()
    except Exception as e:
        print(e)
        return f'An exception occurred: {e}'

app = Flask(__name__)

handler = WebhookHandler(cfg['line']['channel_secret'])
line_bot_api = LineBotApi(cfg['line']['channel_access_token'])


@app.route('/')
def hello_world():  # put application's code here
    return 'Hello World!'


@app.route("/callback", methods=["POST"])
def callback():
    # get X-Line-Signature header value
    signature = request.headers["X-Line-Signature"]
    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # parse webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


def unauthorized(user_id, req):
    filename = f'{user_id}.json'
    key = req.headers.get('X-API-Key')

    if key is None:
        return True

    if not os.path.exists(filename):
        return True

    with open(filename, encoding='utf-8') as f:
        j = json.load(f)

    key_hash = hashlib.sha256(key.encode()).hexdigest()

    if key_hash != j['api_key_hash']:
        return True

    return False

@app.route("/api/users/<user_id>/history", methods=["GET"])
def api_get_history(user_id):
    if unauthorized(user_id, request):
        return jsonify({"error": "unauthorized"}), 401

    filename = f'{user_id}.json'

    with open(filename, encoding='utf-8') as f:
        j = json.load(f)

    history = []

    for item in j['history']:
        if not item['deleted']:
            item.pop("deleted", None)
            history.append(item)

    return json.dumps({
        "user_id": user_id,
        "history": history,
    }, ensure_ascii=False, indent=2)


@app.route("/api/users/<user_id>/history/<int:timestamp>", methods=["GET"])
def api_get_message(user_id, timestamp):
    if unauthorized(user_id, request):
        return jsonify({"error": "unauthorized"}), 401

    filename = f'{user_id}.json'

    with open(filename, encoding='utf-8') as f:
        j = json.load(f)

    for item in j['history']:
        if item['timestamp'] == timestamp:
            if item['deleted']:
                break
            item.pop("deleted", None)
            return json.dumps({
                "user_id": user_id,
                "message": item
            }, ensure_ascii=False, indent=2)

    return jsonify({"error": "not found"}), 404


@app.route("/api/users/<user_id>/history/<int:timestamp>", methods=["DELETE"])
def api_delete_message(user_id, timestamp):
    if unauthorized(user_id, request):
        return jsonify({"error": "unauthorized"}), 401

    filename = f'{user_id}.json'

    with open(filename, encoding='utf-8') as f:
        j = json.load(f)

    for item in j['history']:
        if item['timestamp'] == timestamp:
            if item['deleted']:
                break
            item['deleted'] = True
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(j, f, ensure_ascii=False, indent=2)
            return jsonify({"status": "success"}), 200

    return jsonify({"error": "not found"}), 404


def azure_translate(user_input):
    try:
        target_languages = ["en"]
        input_text_elements = [user_input]

        text_translator = TextTranslationClient(
            credential=AzureKeyCredential(cfg["AzureTranslator"]["Key"]),
            endpoint=cfg["AzureTranslator"]["EndPoint"],
            region=cfg["AzureTranslator"]["Region"],
        )

        response = text_translator.translate(
            body=input_text_elements, to_language=target_languages
        )
        return response[0].translations[0].text

    except HttpResponseError as exception:
        print(f"Error Code: {exception.error}")
        print(f"Message: {exception.error.message}")
        return f"An error has occurred: {exception}"


@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    filename = f'{event.source.user_id}.json'

    if not os.path.exists(filename):
        with open(filename, "w", encoding='utf-8') as f:
            json.dump({
                "user_id": event.source.user_id,
                "api_key_hash": '',
                "history": [],
            }, f, ensure_ascii=False, indent=2)

    text = event.message.text

    if text.lower() == 'api-keygen':
        key = secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(key.encode()).hexdigest()

        reply_message = TextSendMessage(text=key)

        line_bot_api.reply_message(
            event.reply_token,
            reply_message,
        )

        reply_message.text = key_hash

        with open(filename, 'r', encoding='utf-8') as f:
            j = json.load(f)

        j['api_key_hash'] = key_hash

        j['history'].append({
            "timestamp": event.timestamp,
            "event": json.loads(str(event)),
            "reply_message": json.loads(str(reply_message)),
            "deleted": False,
        })

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(j, f, ensure_ascii=False, indent=2)

        return

    elif text.lower() == 'sticker':
        reply_message = StickerSendMessage(
            package_id='11539',
            sticker_id=f'{random.randint(52114110, 52114149)}'
        )

    elif text.lower() == 'image':
        reply_message = ImageSendMessage(
            original_content_url='https://www.yzu.edu.tw/aboutyzu/images/main/origin-logo.png',
            preview_image_url='https://www.yzu.edu.tw/aboutyzu/images/main/origin-logo.png'
        )

    elif text.lower() == 'video':
        reply_message = VideoSendMessage(
            original_content_url='https://raw.githubusercontent.com/openai/openai-cookbook/main/examples/data/bison.mp4',
            preview_image_url='https://raw.githubusercontent.com/openai/openai-cookbook/main/images/openai-cookbook-white.png',
        )

    elif text.lower() == 'location':
        reply_message = LocationSendMessage(
            title = "LINEヤフー株式会社 本社",
            address='1-3 Kioicho, Chiyoda-ku, Tokyo, 102-8282, Japan',
            latitude = 35.67966,
            longitude = 139.73669
        )

    elif text.lower().startswith('gemini:'):
        reply_message = TextMessage(
            text=ask_gemini(
                text.removeprefix('Gemini:').removeprefix('gemini:'),
            )
        )

    elif text.lower().startswith('translate:'):
        reply_message = TextMessage(
            text=azure_translate(
                text.removeprefix('Translate:').removeprefix('translate:')
            )
        )

    else:
        reply_message = TextMessage(
            text=f'''[基本指令]
用法：`<指令>`
例如：sticker
將會回覆一張貼圖
- `help` 傳送幫助
- `sticker` 傳送貼圖
- `image` 傳送圖片
- `video` 傳送影片
- `location` 傳送地點

[Gemini/AI 指令]
用法：`<指令>:<內容>`
例如：gemini:哈囉
將會回覆 gemini 對哈囉的回答
- `gemini` 詢問 Gemini，並傳送回答
- `translate` 將內容翻譯成英文'''
        )

    line_bot_api.reply_message(
        event.reply_token,
        reply_message
    )

    with open(filename, 'r', encoding='utf-8') as f:
        j = json.load(f)

    j['history'].append({
        "timestamp": event.timestamp,
        "event": json.loads(str(event)),
        "reply_message": json.loads(str(reply_message)),
        "deleted": False,
    })

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(j, f, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    app.run()
