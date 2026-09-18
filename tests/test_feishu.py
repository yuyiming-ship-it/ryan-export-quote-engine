import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from export_quote.feishu import _extract_json_document, folder_token, read_json_source, upload_snapshot


class Completed:
    returncode = 0
    stderr = ''
    def __init__(self, body):
        self.stdout = json.dumps(body, ensure_ascii=False)


class FeishuAdapterTests(unittest.TestCase):
    def test_extract_executable_json_block(self):
        text = '说明\n```json\n{"schema_version":"1.0","status":"pending"}\n```'
        self.assertEqual(_extract_json_document(text)['status'], 'pending')

    @patch('export_quote.feishu.shutil.which', return_value='/bin/lark-cli')
    @patch('export_quote.feishu.subprocess.run')
    def test_read_feishu_doc(self, run, _which):
        content = '```json\n{"schema_version":"1.0","version":"x"}\n```'
        run.return_value = Completed({'ok': True, 'data': {'document': {'content': content}}})
        value = read_json_source('https://example.larksuite.com/docx/abc')
        self.assertEqual(value['version'], 'x')
        self.assertIn('docs', run.call_args.args[0])

    def test_folder_url_required(self):
        self.assertEqual(folder_token('https://example.larksuite.com/drive/folder/fld123'), 'fld123')
        with self.assertRaises(ValueError):
            folder_token('https://example.larksuite.com/docx/abc')

    @patch('export_quote.feishu.shutil.which', return_value='/bin/lark-cli')
    @patch('export_quote.feishu.subprocess.run')
    def test_snapshot_upload_is_idempotent(self, run, _which):
        run.return_value = Completed({'ok': True, 'data': {'file_token': 'file1'}})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / 'hash.json'
            snapshot.write_text('{}')
            markers = root / 'markers'
            url = 'https://example.larksuite.com/drive/folder/fld123'
            self.assertEqual(upload_snapshot(snapshot, url, markers)['file_token'], 'file1')
            self.assertEqual(upload_snapshot(snapshot, url, markers)['file_token'], 'file1')
            self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
