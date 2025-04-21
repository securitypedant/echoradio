from mods.utils import ensure_data_dir

def check_app_infra(app):
    ensure_data_dir('data')
    ensure_data_dir('data/supervisord_configs')