import base64
import json
import os
import unittest
from unittest.mock import patch
os.environ.setdefault('DATABASE_URL', 'sqlite://')
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

class SchemasTests(unittest.TestCase):
    def test_page_requires_session_and_renders_observations(self):
        from app.main import app, settings
        with patch('app.main.load_request_ui_texts', return_value={}), TestClient(app) as client:
            self.assertEqual(client.get('/schemas', follow_redirects=False).status_code, 303)
            cookie = TimestampSigner(settings.session_secret).sign(base64.b64encode(json.dumps({'portal_user': settings.portal_username}).encode())).decode()
            client.cookies.set('session', cookie)
            landing = client.get('/schemas')
            self.assertNotIn('schemas-network', landing.text)
            self.assertIn('PostgreSQL', landing.text)
            empty = client.get('/schemas?engine=oracle')
            self.assertNotIn('schemas-network', empty.text)
            response = client.get('/schemas?engine=postgresql&database=aml')
            self.assertEqual(response.status_code, 200)
            for text in ('SCHEMAS', '10.210.120.70:5000', '10.210.120.72:5432', '10.210.120.13', '10.210.120.16'):
                self.assertIn(text, response.text)
            self.assertIn('не live-мониторинг', response.text)
