"""Stateful parser for the observed DeepSeek Web SSE fragment protocol."""
import json

class StreamState:
    def __init__(self):
        self.message_id = None
        self.status = None
        self.closed = False
        self.text = {'text': '', 'thinking': ''}
        self.kind = 'text'
        self.continuation = False

    def _snapshot(self, fragments):
        if not isinstance(fragments, list): return []
        result = []
        for fragment in fragments:
            if not isinstance(fragment, dict): continue
            kind = 'thinking' if fragment.get('type') == 'THINK' else 'text'
            content = fragment.get('content')
            if not isinstance(content, str): continue
            previous = self.text[kind]
            if content.startswith(previous) and len(content) > len(previous):
                added = content[len(previous):]
                self.text[kind] = content
                result.append(self._chunk(added, kind))
        if fragments and isinstance(fragments[-1], dict):
            self.kind = 'thinking' if fragments[-1].get('type') == 'THINK' else 'text'
        return result

    def _chunk(self, content, kind):
        return {'type': kind, 'content': content, 'message_id': self.message_id}

    def feed(self, line):
        if not line: return []
        if line.startswith(b'event:'):
            self.closed = line[6:].strip() == b'close'
            return []
        if not line.startswith(b'data:'): return []
        payload = line[5:].strip()
        if payload == b'[DONE]': self.closed = True; return []
        try: obj = json.loads(payload)
        except ValueError: raise ValueError('Invalid DeepSeek stream JSON')
        if not isinstance(obj, dict): return []
        self.message_id = obj.get('response_message_id') or self.message_id
        choices = obj.get('choices') or []
        if choices:
            choice = choices[0]; delta = choice.get('delta') or {}
            content = delta.get('content') or ''
            if choice.get('finish_reason') == 'stop':
                self.status = 'FINISHED'; self.closed = True
            if content:
                self.message_id = obj.get('message_id') or delta.get('message_id') or self.message_id
                self.text['text'] += content
                return [self._chunk(content, 'text')]
        value = obj.get('v')
        if isinstance(value, dict) and isinstance(value.get('response'), dict):
            response = value['response']
            self.message_id = response.get('message_id') or self.message_id
            self.status = response.get('status') or self.status
            return self._snapshot(response.get('fragments'))
        path = obj.get('p')
        if path == 'response/status' and isinstance(value, str):
            self.status = value
            if value in ('FINISHED', 'INCOMPLETE'): self.closed = True
            self.continuation = False
            return []
        if path == 'response/fragments' and isinstance(value, list):
            self.continuation = False
            return self._snapshot(value)
        if path == 'response/fragments/-1/content' and obj.get('o') == 'APPEND' and isinstance(value, str):
            self.continuation = True
        elif set(obj) == {'v'} and self.continuation and isinstance(value, str):
            pass
        else:
            return []
        if not value: return []
        self.text[self.kind] += value
        return [self._chunk(value, self.kind)]
