import os
import sys
from pathlib import Path

from flask import Flask, url_for

from core.settings import build_mysql_uri
from routes import register_blueprints
from services.dca_plan_service import start_dca_plan_scheduler
from services.fund_transaction_service import start_pending_transaction_confirmation_scheduler
from services.user_fund_service import init_database


def create_app():
    app = Flask(__name__, static_folder='static', template_folder='templates')
    app.config['DB_URI'] = build_mysql_uri()
    app.config['DB_URI_MASKED'] = build_mysql_uri(mask_password=True)

    init_database()
    register_blueprints(app)
    if os.getenv('WERKZEUG_RUN_MAIN') == 'true' or os.getenv('FLASK_DEBUG', '1').strip().lower() in ('0', 'false', 'no'):
        start_pending_transaction_confirmation_scheduler()
        start_dca_plan_scheduler()

    def asset_url(filename):
        normalized = str(filename or '').lstrip('/')
        if normalized.startswith('static/'):
            normalized = normalized[7:]

        version = '1'
        try:
            asset_path = Path(app.static_folder) / normalized
            version = str(int(asset_path.stat().st_mtime))
        except OSError:
            pass

        return url_for('static', filename=normalized, v=version)

    @app.context_processor
    def inject_asset_helpers():
        return {
            'asset_url': asset_url,
        }

    return app


app = create_app()


if __name__ == '__main__':
    debug_enabled = os.getenv('FLASK_DEBUG', '1').strip().lower() not in ('0', 'false', 'no')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    print('启动基金监控服务...')
    print('请在浏览器访问 http://127.0.0.1:5000')
    print(f'调试模式: {"on" if debug_enabled else "off"}')
    app.run(
        host='127.0.0.1',
        port=5000,
        debug=debug_enabled,
        use_reloader=debug_enabled,
    )
