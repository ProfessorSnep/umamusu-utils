import logging
import sqlite3

from pathlib import Path


ROOT = Path(__file__, '../..')
LOG_ROOT = Path(ROOT, 'logs')
STORAGE_ROOT = Path(ROOT, 'storage')


_girls = None
def get_girls_dict():
    global _girls
    if _girls:
        return _girls

    girls = {}
    with get_master_conn() as master_conn:
        for index, text in master_conn.execute('SELECT "index", "text" FROM "text_data" WHERE "category" = 6'):
            girls[index] = text

    _girls = girls
    return _girls


_support_map = None
def get_support_to_char_map():
    global _support_map
    if _support_map:
        return _support_map
    
    support_map = {}
    with get_master_conn() as master_conn:
        for support_id, chara_id in master_conn.execute('SELECT "id", "chara_id" FROM "support_card_data"'):
            support_map[support_id] = chara_id
    
    _support_map = support_map
    return _support_map


def get_logger(name: str):
    logger = logging.getLogger(name)
    if name == '__main__':
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(levelname)s\t%(message)s'))
    else:
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(filename=Path(LOG_ROOT, f'{name}.log'), mode='w+', encoding='utf8')

    logger.addHandler(handler)
    return logger


def get_storage_folder(folder: str):
    path = Path(STORAGE_ROOT, folder)
    path.mkdir(exist_ok=True)
    return path


def get_meta_conn():
    return sqlite3.connect(Path(STORAGE_ROOT, 'meta'))


def get_master_conn():
    return sqlite3.connect(Path(STORAGE_ROOT, 'master.mdb'))
