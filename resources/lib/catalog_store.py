"""Local profile storage, with transactional updates and no saved credentials."""
import json
import os
import sqlite3
import time
import unicodedata


class Store:
    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute('CREATE TABLE IF NOT EXISTS favorites (kind TEXT, id INTEGER, data TEXT NOT NULL, added INTEGER NOT NULL, PRIMARY KEY(kind,id))')
        self.db.execute('CREATE TABLE IF NOT EXISTS searches (kind TEXT, normalized TEXT, query TEXT NOT NULL, used INTEGER NOT NULL, PRIMARY KEY(kind,normalized))')
        self.db.commit()

    def close(self):
        self.db.close()

    def favorite_keys(self):
        return set(self.db.execute('SELECT kind,id FROM favorites').fetchall())

    def favorites(self, kind='all'):
        sql, args = 'SELECT data FROM favorites', ()
        if kind in ('movie', 'tv'):
            sql, args = sql + ' WHERE kind=?', (kind,)
        return [json.loads(row[0]) for row in self.db.execute(sql + ' ORDER BY added DESC, rowid DESC', args)]

    def add_favorite(self, summary):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO favorites VALUES (?,?,?,?)',
                            (summary['media_type'], int(summary['id']), json.dumps(summary, ensure_ascii=False), time.time_ns()))

    def remove_favorite(self, kind, media_id):
        with self.db:
            self.db.execute('DELETE FROM favorites WHERE kind=? AND id=?', (kind, int(media_id)))

    def remember(self, kind, query):
        query = ' '.join(query.split()).strip()[:250]
        normalized = unicodedata.normalize('NFKC', query).casefold()
        if kind not in ('movie', 'tv', 'multi') or not normalized:
            return
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO searches VALUES (?,?,?,?)', (kind, normalized, query, time.time_ns()))
            self.db.execute('DELETE FROM searches WHERE rowid NOT IN (SELECT rowid FROM searches ORDER BY used DESC LIMIT 100)')

    def searches(self):
        return [dict(kind=k, query=q) for k, q in self.db.execute('SELECT kind,query FROM searches ORDER BY used DESC')]

    def remove_search(self, kind, query):
        normalized = unicodedata.normalize('NFKC', ' '.join(query.split()).strip()[:250]).casefold()
        with self.db:
            self.db.execute('DELETE FROM searches WHERE kind=? AND normalized=?', (kind, normalized))

    def clear_searches(self):
        with self.db:
            self.db.execute('DELETE FROM searches')
