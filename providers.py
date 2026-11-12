"""Bốn provider cùng một interface. Không chứa agent loop."""
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(Path(__file__).resolve().parent / '.env')

CONFIG = {
    'openai': ('OPENAI_API_KEY', 'https://api.openai.com/v1/chat/completions'),
    'gemini': ('GEMINI_API_KEY', 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'),
    'openrouter': ('OPENROUTER_API_KEY', 'https://openrouter.ai/api/v1/chat/completions'),
    'anthropic': ('ANTHROPIC_API_KEY', 'https://api.anthropic.com/v1/messages'),
}


def _http_error_message(code, body=None):
    if code == 401:
        return 'Provider từ chối request: sai API key hoặc quyền truy cập không hợp lệ.'
    if code == 403:
        return 'Provider từ chối request: tài khoản/key không có quyền hoặc bị khóa.'
    if code == 404:
        return 'Provider trả 404: endpoint/model không tồn tại hoặc chưa được kích hoạt.'
    if code == 429:
        return 'Provider báo rate limit (429): quá nhiều request, hãy chờ một lúc rồi thử lại.'
    if 500 <= code < 600:
        return f'Provider đang lỗi phía server ({code}): thử lại sau ít phút.'
    if body:
        return f'Provider trả HTTP {code}: {body[:300]}'
    return f'Provider trả HTTP {code}: kiểm tra cấu hình key, model và payload.'


def post_json(url, headers, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', **headers},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode('utf-8', 'ignore')
        except Exception:
            body = None
        raise RuntimeError(_http_error_message(exc.code, body)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'Không kết nối được provider: {exc.reason}. Kiểm tra mạng hoặc endpoint của provider.') from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError('Provider trả về dữ liệu không phải JSON hợp lệ.') from exc
    except Exception as exc:
        raise RuntimeError(f'Lỗi không xác định khi gọi provider: {type(exc).__name__}: {exc}') from exc


class Provider:
    """complete(messages, schemas) -> {message, calls, finish, usage}.

    messages: system/user/assistant/tool theo format Chat Completions. message trả về
    cần được append nguyên vẹn; tool result có role, tool_call_id, content (JSON string).
    """
    def __init__(self, name, model):
        if name not in CONFIG:
            raise ValueError(f'Provider không hợp lệ: {name}')
        if not model:
            raise ValueError('Cần đặt MODEL là model có hỗ trợ tool calling.')
        self.name, self.model = name, model
        key_name, self.url = CONFIG[name]
        self.key = os.getenv(key_name)
        if not self.key:
            raise ValueError(f'Thiếu {key_name}. Hãy tạo file .env và set đúng key.')

    def complete(self, messages, schemas):
        if self.name == 'anthropic':
            return self._anthropic(messages, schemas)
        payload = {'model': self.model, 'messages': messages, 'max_tokens': 1024}
        if schemas:
            payload['tools'] = schemas
        data = post_json(self.url, {'Authorization': f'Bearer {self.key}'}, payload)

        if 'choices' not in data or not data['choices']:
            raise RuntimeError('Provider không trả về choices hợp lệ.')

        choice = data['choices'][0]
        message = choice.get('message', {})
        calls = []
        for call in message.get('tool_calls', []):
            function = call.get('function', {})
            name = function.get('name')
            arguments = function.get('arguments') or '{}'
            try:
                args = json.loads(arguments)
            except json.JSONDecodeError:
                args = {'_invalid_json_arguments': arguments}
            if not isinstance(args, dict):
                args = {'_invalid_json_arguments': arguments}
            calls.append({
                'id': call.get('id'),
                'name': name,
                'arguments': json.dumps(args, ensure_ascii=False),
            })
        return {'message': message, 'calls': calls, 'finish': choice.get('finish_reason'), 'usage': data.get('usage', {})}

    def _anthropic(self, messages, schemas):
        system = '\n'.join(m['content'] for m in messages if m['role'] == 'system')
        native = []
        for m in messages:
            if m['role'] == 'system':
                continue
            if m['role'] == 'assistant':
                blocks = []
                if m.get('content'):
                    blocks.append({'type': 'text', 'text': m['content']})
                for call in m.get('tool_calls', []):
                    blocks.append({'type': 'tool_use', 'id': call['id'], 'name': call['function']['name'], 'input': json.loads(call['function']['arguments'])})
                native.append({'role': 'assistant', 'content': blocks})
            elif m['role'] == 'tool':
                block = {'type': 'tool_result', 'tool_use_id': m['tool_call_id'], 'content': m['content']}
                if native and native[-1]['role'] == 'user' and isinstance(native[-1]['content'], list):
                    native[-1]['content'].append(block)
                else:
                    native.append({'role': 'user', 'content': [block]})
            else:
                native.append({'role': 'user', 'content': m['content']})
        tools = [{'name': x['function']['name'], 'description': x['function']['description'], 'input_schema': x['function']['parameters']} for x in schemas]
        payload = {'model': self.model, 'max_tokens': 1024, 'system': system, 'messages': native}
        if tools:
            payload['tools'] = tools
        data = post_json(self.url, {'x-api-key': self.key, 'anthropic-version': '2023-06-01'}, payload)
        blocks = data['content']
        calls = [{'id': b['id'], 'name': b['name'], 'arguments': json.dumps(b['input'], ensure_ascii=False)} for b in blocks if b['type'] == 'tool_use']
        text = '\n'.join(b['text'] for b in blocks if b['type'] == 'text')
        message = {'role': 'assistant', 'content': text or None}
        if calls:
            message['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {'name': c['name'], 'arguments': c['arguments']}} for c in calls]
        reason = {'end_turn': 'stop', 'tool_use': 'tool_calls', 'max_tokens': 'length'}.get(data.get('stop_reason'), data.get('stop_reason'))
        return {'message': message, 'calls': calls, 'finish': reason, 'usage': data.get('usage', {})}
