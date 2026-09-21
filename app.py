"""NutriPedia: biblioteca sobre alimentação complementar, para portefólio."""
import logging
import os
import secrets
import sqlite3
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, abort, g, jsonify, render_template, request, session
from werkzeug.exceptions import HTTPException

from seed_data import CATEGORIES, DEMO_CAMPAIGNS, DEMO_RESOURCES, DEMO_VERSION, OLD_DEMO_URLS

API_ERROR_MESSAGES = {403: 'Pedido não autorizado.', 404: 'Recurso não encontrado.',
                      405: 'Método não permitido.'}

ROOT = Path(__file__).parent
TRUSTED_SOURCE_DOMAINS = ('who.int', 'dgs.pt', 'efsa.europa.eu')
SOURCE_VERIFIED_AT = '21 set. 2026'
logger = logging.getLogger(__name__)


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
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        logger.warning('SECRET_KEY não definida: a gerar uma chave temporária válida apenas '
                        'para este processo. As sessões e os tokens CSRF existentes ficam '
                        'inválidos a cada reinício. Define SECRET_KEY em produção (ver .env.example).')
        secret_key = secrets.token_hex(32)
    app.config.update(SECRET_KEY=secret_key,
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
        if not version or version['value'] != DEMO_VERSION:
            placeholders = ','.join('?' for _ in OLD_DEMO_URLS)
            db().execute(f'DELETE FROM resources WHERE url IN ({placeholders})', OLD_DEMO_URLS)
            db().execute('''UPDATE resources
                            SET title=?, specialty=?, description=?
                            WHERE url=?''', DEMO_RESOURCES[0][:3] + (DEMO_RESOURCES[0][3],))
            for resource in DEMO_RESOURCES:
                db().execute('''INSERT INTO resources (title, specialty, description, url)
                                SELECT ?, ?, ?, ? WHERE NOT EXISTS
                                (SELECT 1 FROM resources WHERE url = ?)''', (*resource, resource[3]))
            db().execute("INSERT INTO app_meta (key, value) VALUES ('demo_version', ?) ON CONFLICT(key) DO UPDATE SET value=?",
                         (DEMO_VERSION, DEMO_VERSION))
            db().commit()
        if not db().execute('SELECT COUNT(*) FROM campaigns').fetchone()[0]:
            db().executemany('''INSERT INTO campaigns
                (name, sponsor, audience, channel, status, reach, opens, clicks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', DEMO_CAMPAIGNS)
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

    @app.errorhandler(HTTPException)
    def handle_api_error(error):
        if not request.path.startswith('/api/'):
            return error
        message = API_ERROR_MESSAGES.get(error.code, 'Não foi possível concluir o pedido.')
        return jsonify(error=message), error.code

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
