from routes.dashboard_routes import dashboard_bp
from routes.fund_routes import fund_bp
from routes.site_routes import site_bp
from routes.user_routes import user_bp


def register_blueprints(app):
    app.register_blueprint(site_bp)
    app.register_blueprint(fund_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(user_bp)
