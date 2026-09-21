import tempfile
import unittest
from pathlib import Path
from app import create_app


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'test.sqlite'
        self.app = create_app(self.database)
        self.client = self.app.test_client()
        self.client.get('/')
        with self.client.session_transaction() as session:
            self.headers = {'X-CSRF-Token': session['csrf']}
        self.resource = dict(title='Recurso de teste', specialty='Começar aos 6 meses',
                             description='Descrição de exemplo.', url='https://www.who.int/')

    def test_search_ignores_accents_and_combines_filters(self):
        rows = self.client.get('/api/resources?q=alergenicos&specialty=Segurança').json
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['specialty'], 'Segurança')
        self.assertEqual(self.client.get('/api/resources?q=inexistente').json, [])

    def test_create_edit_and_persistence(self):
        response = self.client.post('/api/resources', json=self.resource, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        identifier = response.json['id']
        edited = dict(self.resource, title='Título atualizado')
        self.assertEqual(self.client.put(f'/api/resources/{identifier}', json=edited, headers=self.headers).status_code, 200)
        other_client = create_app(self.database).test_client()
        self.assertEqual(other_client.get('/api/resources?q=atualizado').json[0]['id'], identifier)

    def test_favorites_can_be_added_and_removed(self):
        path = '/api/resources/1/favorite'
        for value in (True, False):
            self.assertEqual(self.client.patch(path, json={'favorite': value}, headers=self.headers).status_code, 200)
            self.assertEqual(len(self.client.get('/api/resources?favorites=1').json), int(value))

    def test_rejects_invalid_data_and_untrusted_links(self):
        for changes in ({'title': ' '}, {'url': 'javascript:alert(1)'},
                        {'url': 'https://example.com/article'},
                        {'specialty': 'Inexistente'}, {'description': 42}):
            self.assertEqual(self.client.post('/api/resources', json=dict(self.resource, **changes), headers=self.headers).status_code, 400)

    def test_protects_writes_and_missing_resources(self):
        self.assertEqual(self.client.post('/api/resources', json=self.resource).status_code, 403)
        self.assertEqual(self.client.put('/api/resources/999', json=self.resource, headers=self.headers).status_code, 404)

    def test_campaign_workflow_uses_aggregate_metrics(self):
        campaign = dict(name='Campanha de teste', sponsor='Marca demo',
                        audience='Pediatria · Portugal', channel='Email')
        response = self.client.post('/api/campaigns', json=campaign, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        identifier = response.json['id']
        created = next(item for item in self.client.get('/api/campaigns').json if item['id'] == identifier)
        self.assertEqual((created['reach'], created['opens'], created['clicks']), (0, 0, 0))
        response = self.client.patch(f'/api/campaigns/{identifier}/status',
                                     json={'status': 'active'}, headers=self.headers)
        self.assertEqual(response.status_code, 200)

    def test_campaign_rejects_invalid_channel_and_status(self):
        campaign = dict(name='Campanha de teste', sponsor='Marca demo',
                        audience='Pediatria', channel='Canal inventado')
        self.assertEqual(self.client.post('/api/campaigns', json=campaign, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.patch('/api/campaigns/1/status',
                         json={'status': 'invalid'}, headers=self.headers).status_code, 400)


if __name__ == '__main__':
    unittest.main()
