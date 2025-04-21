from mods.utils import ensure_data_dir

def check_app_infra():
    ensure_data_dir('data/streams')
    ensure_data_dir('data/supervisord_configs')
    ensure_data_dir('data/logs')