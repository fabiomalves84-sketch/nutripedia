"""NutriPedia: biblioteca sobre alimentação complementar, para portefólio."""
import os
import secrets
import sqlite3
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, abort, g, jsonify, render_template, request, session

ROOT = Path(__file__).parent
CATEGORIES = ['Começar aos 6 meses', 'Frequência e porções', 'Texturas', 'Variedade alimentar', 'Segurança', 'Alimentação responsiva', 'Vacinação']
TRUSTED_SOURCE_DOMAINS = ('who.int', 'dgs.pt', 'efsa.europa.eu')
SOURCE_VERIFIED_AT = '21 set. 2026'
DEMO_RESOURCES = [
    ('Orientação completa dos 6 aos 23 meses', 'Começar aos 6 meses', 'Recomendações da OMS baseadas em evidência para crianças amamentadas e não amamentadas.', 'https://www.who.int/publications/i/item/9789240081864'),
    ('Quando começar a alimentação complementar', 'Começar aos 6 meses', 'Visão geral da OMS sobre o início aos 6 meses e a progressão da alimentação.', 'https://www.who.int/health-topics/complementary-feeding'),
    ('Frequência mínima das refeições', 'Frequência e porções', 'Indicador e princípios da OMS para o número de refeições entre os 6 e os 23 meses.', 'https://www.who.int/data/gho/data/indicators/indicator-details/GHO/minimum-meal-frequency-6-23-months'),
    ('Alimentação saudável dos 0 aos 6 anos', 'Variedade alimentar', 'Manual português da DGS para profissionais e educadores, com orientações por idade.', 'https://alimentacaosaudavel.dgs.pt/alimentacao-saudavel-dos-0-aos-6-anos/'),
    ('Texturas e progressão dos alimentos', 'Texturas', 'Resumo da OMS sobre consistência, variedade e alimentos que a criança pode segurar.', 'https://www.who.int/news-room/fact-sheets/detail/infant-and-young-child-feeding'),
    ('Introdução de alimentos potencialmente alergénicos', 'Segurança', 'Página da EFSA, em português, sobre a introdução de alimentos e alergénios na alimentação complementar.', 'https://www.efsa.europa.eu/pt/glossary/complementary-feeding'),
    ('Alimentação adequada e segura', 'Segurança', 'Orientação da OMS sobre higiene, preparação e armazenamento seguro de alimentos complementares.', 'https://www.who.int/publications/i/item/924154614X'),
    ('Reconhecer fome e saciedade', 'Alimentação responsiva', 'Base de evidência da OMS sobre sinais da criança, pressão para comer e exposição repetida.', 'https://www.who.int/news-room/articles-detail/call-for-authors-systematic-reviews-on-feeding-of-infants-and-young-children-6-23-months-of-age-2set'),
    ('Programa Nacional de Vacinação', 'Vacinação', 'Livro Azul da DGS: referencial técnico nacional para vacinação e outras estratégias de imunização em Portugal.', 'https://www.dgs.pt/paginas-de-sistema/saude-de-a-a-z/programa-nacional-de-vacinacao/livro-azul-da-imunizacao.aspx'),
    ('Esquema geral recomendado do PNV', 'Vacinação', 'Consulta o esquema geral recomendado pela DGS. Confirma sempre o Boletim de Saúde Infantil e as indicações da equipa de saúde.', 'https://www.dgs.pt/paginas-de-sistema/saude-de-a-a-z/programa-nacional-de-vacinacao/livro-azul-da-imunizacao/parte-1-programa-nacional-de-vacinacao-2025.aspx'),
]
OLD_DEMO_URLS = [
    'https://www.who.int/health-topics', 'https://www.dgs.pt/',
    'https://www.who.int/health-topics/cardiovascular-diseases',
    'https://www.who.int/health-topics/child-health',
    'https://www.who.int/health-topics/mental-health',
    'https://www.who.int/health-topics/patient-safety',
    'https://www.dgs.pt/pns-e-programas/programas-de-saude/saude-infantil-e-juvenil.aspx',
    'https://www.who.int/tools/child-growth-standards/standards',
    'https://www.who.int/news-room/questions-and-answers/item/child-growth-standards',
    'https://www.dgs.pt/paginas-de-sistema/saude-de-a-a-z/programa-nacional-de-vacinacao/livro-azul-da-imunizacao.aspx',
    'https://www.who.int/publications/i/item/9789241510219',
    'https://www.who.int/news-room/fact-sheets/detail/adolescent-mental-health',
    'https://www.who.int/health-topics/early-child-development',
    'https://www.who.int/tools/elena/interventions/complementary-feeding',
    'https://www.efsa.europa.eu/en/glossary/complementary-feeding',
]


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.casefold())
                   if unicodedata.category(c) != 'Mn')


def is_trusted_source(url):
    """Aceita apenas fontes HTTPS de entidades de saúde autorizadas."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ''
    except ValueError:
        return False
    return (parsed.scheme == 'https' and not parsed.username and not parsed.password
            and any(hostname == domain or hostname.endswith(f'.{domain}')
                    for domain in TRUSTED_SOURCE_DOMAINS))


def source_metadata(url):
    """Apresenta a entidade e o idioma sem duplicar estes dados na base de dados."""
    parsed = urlparse(url)
    hostname = parsed.hostname or ''
    if hostname == 'dgs.pt' or hostname.endswith('.dgs.pt'):
        return {'source_name': 'DGS', 'source_language': 'Português'}
    if hostname == 'efsa.europa.eu' or hostname.endswith('.efsa.europa.eu'):
        return {'source_name': 'EFSA', 'source_language': 'Português' if '/pt/' in parsed.path else 'Inglês'}
    return {'source_name': 'OMS', 'source_language': 'Inglês'}


def create_app(database=None):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY') or secrets.token_hex(32),
                      DATABASE=str(database or ROOT / 'library.sqlite'),
                      MAX_CONTENT_LENGTH=16384, SESSION_COOKIE_SAMESITE='Strict')

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(app.config['DATABASE'])
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(error=None):
        connection = g.pop('db', None)
        if connection:
            connection.close()

    with app.app_context():
        db().execute('''CREATE TABLE IF NOT EXISTS resources (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, specialty TEXT NOT NULL,
            description TEXT NOT NULL, url TEXT NOT NULL, favorite INTEGER NOT NULL DEFAULT 0)''')
        db().execute('CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db().execute('''CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, sponsor TEXT NOT NULL,
            audience TEXT NOT NULL, channel TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
            reach INTEGER NOT NULL DEFAULT 0, opens INTEGER NOT NULL DEFAULT 0,
            clicks INTEGER NOT NULL DEFAULT 0)''')
        version = db().execute("SELECT value FROM app_meta WHERE key='demo_version'").fetchone()
        if not version or version['value'] != '7':
            placeholders = ','.join('?' for _ in OLD_DEMO_URLS)
            db().execute(f'DELETE FROM resources WHERE url IN ({placeholders})', OLD_DEMO_URLS)
            db().execute('''UPDATE resources
                            SET title=?, specialty=?, description=?
                            WHERE url=?''', DEMO_RESOURCES[0][:3] + (DEMO_RESOURCES[0][3],))
            for resource in DEMO_RESOURCES:
                db().execute('''INSERT INTO resources (title, specialty, description, url)
                                SELECT ?, ?, ?, ? WHERE NOT EXISTS
                                (SELECT 1 FROM resources WHERE url = ?)''', (*resource, resource[3]))
            db().execute("INSERT INTO app_meta (key, value) VALUES ('demo_version', '7') ON CONFLICT(key) DO UPDATE SET value='7'")
            db().commit()
        if not db().execute('SELECT COUNT(*) FROM campaigns').fetchone()[0]:
            db().executemany('''INSERT INTO campaigns
                (name, sponsor, audience, channel, status, reach, opens, clicks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', [
                ('Alimentação complementar 6–23 meses', 'Marca demonstrativa', 'Pediatria · Portugal', 'Mensagem in-app', 'active', 8420, 5110, 1480),
                ('Atualização científica em nutrição infantil', 'Parceiro demonstrativo', 'Pediatria · Portugal', 'Email', 'draft', 0, 0, 0),
            ])
            db().commit()

    @app.before_request
    def csrf_protection():
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            expected = session.get('csrf')
            if not expected or not secrets.compare_digest(expected, request.headers.get('X-CSRF-Token', '')):
                abort(403)

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.get('/')
    def index():
        session.setdefault('csrf', secrets.token_hex(32))
        return render_template('index.html', categories=CATEGORIES, csrf=session['csrf'])

    @app.get('/campaigns')
    def campaigns_page():
        session.setdefault('csrf', secrets.token_hex(32))
        return render_template('campaigns.html', csrf=session['csrf'])

    @app.get('/api/resources')
    def resources():
        rows = [dict(row) for row in db().execute('SELECT * FROM resources ORDER BY title COLLATE NOCASE')]
        for row in rows:
            row.update(source_metadata(row['url']))
            row['source_verified_at'] = SOURCE_VERIFIED_AT
        query = normalize(request.args.get('q', '').strip())
        specialty = request.args.get('specialty', '')
        return jsonify([r for r in rows if
                        (not query or query in normalize(r['title'] + ' ' + r['description'])) and
                        (not specialty or r['specialty'] == specialty) and
                        (request.args.get('favorites') != '1' or r['favorite'])])

    @app.route('/api/resources', methods=['POST'])
    @app.route('/api/resources/<int:resource_id>', methods=['PUT'])
    def save_resource(resource_id=None):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='Envia um recurso válido.'), 400
        fields = {}
        for key, maximum in [('title', 120), ('specialty', 60), ('description', 1000), ('url', 2000)]:
            value = data.get(key)
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
                return jsonify(error=f'O campo {key} é obrigatório e aceita até {maximum} caracteres.'), 400
            fields[key] = value.strip()
        if not is_trusted_source(fields['url']) or fields['specialty'] not in CATEGORIES:
            return jsonify(error='Seleciona uma ligação HTTPS da OMS, DGS ou EFSA e um tema válido.'), 400
        values = tuple(fields[key] for key in ('title', 'specialty', 'description', 'url'))
        if resource_id is None:
            cursor = db().execute('INSERT INTO resources (title, specialty, description, url) VALUES (?, ?, ?, ?)', values)
            resource_id = cursor.lastrowid
        else:
            cursor = db().execute('UPDATE resources SET title=?, specialty=?, description=?, url=? WHERE id=?', (*values, resource_id))
            if not cursor.rowcount:
                abort(404)
        db().commit()
        return jsonify(id=resource_id), 201 if request.method == 'POST' else 200

    @app.patch('/api/resources/<int:resource_id>/favorite')
    def favorite(resource_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or type(data.get('favorite')) is not bool:
            return jsonify(error='Indica se pretendes guardar o favorito.'), 400
        cursor = db().execute('UPDATE resources SET favorite=? WHERE id=?', (int(data['favorite']), resource_id))
        if not cursor.rowcount:
            abort(404)
        db().commit()
        return jsonify(ok=True)

    @app.get('/api/campaigns')
    def campaigns():
        return jsonify([dict(row) for row in db().execute(
            'SELECT * FROM campaigns ORDER BY id DESC')])

    @app.post('/api/campaigns')
    def create_campaign():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='Envia uma campanha válida.'), 400
        fields = {}
        for key, maximum in [('name', 120), ('sponsor', 120), ('audience', 120)]:
            value = data.get(key)
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
                return jsonify(error=f'O campo {key} é obrigatório.'), 400
            fields[key] = value.strip()
        channel = data.get('channel')
        if channel not in {'Mensagem in-app', 'Email', 'Redes sociais'}:
            return jsonify(error='Seleciona um canal válido.'), 400
        cursor = db().execute('''INSERT INTO campaigns (name, sponsor, audience, channel)
                                 VALUES (?, ?, ?, ?)''',
                              (fields['name'], fields['sponsor'], fields['audience'], channel))
        db().commit()
        return jsonify(id=cursor.lastrowid), 201

    @app.patch('/api/campaigns/<int:campaign_id>/status')
    def campaign_status(campaign_id):
        data = request.get_json(silent=True)
        status = data.get('status') if isinstance(data, dict) else None
        if status not in {'draft', 'active', 'paused'}:
            return jsonify(error='Estado inválido.'), 400
        cursor = db().execute('UPDATE campaigns SET status=? WHERE id=?', (status, campaign_id))
        if not cursor.rowcount:
            abort(404)
        db().commit()
        return jsonify(ok=True)

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=int(os.environ.get('PORT', '5050')), debug=False)
