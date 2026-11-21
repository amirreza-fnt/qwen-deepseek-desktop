from app.i18n import tr
import sqlite3, json, os, logging
from pathlib import Path

def default_path():
    return Path(os.getenv('LOCALAPPDATA',str(Path.home())))/'DeepSeekDesktop'/'history.sqlite3'


def read_saved_setting(key, default=None, path=None):
    """Read one saved setting without migrating or creating the database (used before the UI starts)."""
    path=Path(path) if path else default_path()
    if not path.exists(): return default
    try:
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=2) as db:
            row=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default
    except (sqlite3.Error, ValueError, TypeError): return default


class Storage:
    def __init__(self, path=None):
        base=Path(os.getenv('LOCALAPPDATA',str(Path.home())))/'DeepSeekDesktop'
        if path is None:
            base.mkdir(parents=True,exist_ok=True); path=base/'history.sqlite3'
        self.path=Path(path)
        self.db=sqlite3.connect(str(self.path),timeout=10)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA busy_timeout=10000')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY, title TEXT NOT NULL, remote_id TEXT, parent_id TEXT, thinking INTEGER DEFAULT 0, search INTEGER DEFAULT 0, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);''')
        existing={r[1] for r in self.db.execute('PRAGMA table_info(messages)')}
        conv_columns={r[1] for r in self.db.execute('PRAGMA table_info(conversations)')}
        needs_migration='status' not in existing or 'pending_id' not in conv_columns
        if needs_migration and self.path.exists() and self.path.stat().st_size:
            backup=self.path.with_suffix('.pre-status.bak')
            if not backup.exists():
                with sqlite3.connect(str(backup)) as target: self.db.backup(target)
        if 'status' not in existing: self.db.execute("ALTER TABLE messages ADD COLUMN status TEXT NOT NULL DEFAULT 'sent'")
        if 'pending_id' not in conv_columns: self.db.execute('ALTER TABLE conversations ADD COLUMN pending_id TEXT')
        if 'provider' not in conv_columns:
            # Conversations created before Qwen support all belong to DeepSeek.
            if not needs_migration and self.db.execute('SELECT 1 FROM conversations LIMIT 1').fetchone():
                backup=self.path.with_suffix('.pre-provider.bak')
                if not backup.exists():
                    with sqlite3.connect(str(backup)) as target: self.db.backup(target)
            self.db.execute("ALTER TABLE conversations ADD COLUMN provider TEXT NOT NULL DEFAULT 'deepseek'")
        conv_columns={r[1] for r in self.db.execute('PRAGMA table_info(conversations)')}
        # Project mode (per conversation): folder, on/off, attached files (JSON list). Added columns only, no data change.
        if 'project_root' not in conv_columns: self.db.execute('ALTER TABLE conversations ADD COLUMN project_root TEXT')
        if 'project_mode' not in conv_columns: self.db.execute('ALTER TABLE conversations ADD COLUMN project_mode INTEGER NOT NULL DEFAULT 0')
        if 'project_files' not in conv_columns: self.db.execute("ALTER TABLE conversations ADD COLUMN project_files TEXT NOT NULL DEFAULT '[]'")
        self.db.executescript('''CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id,id);
        CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status);''')
        self.db.commit()
    def execute(self, sql, args=()):
        try:
            cur=self.db.execute(sql,args); self.db.commit(); return cur
        except sqlite3.Error as error:
            logging.getLogger('deepseek_desktop.backend').error('database_write_failed operation=%s error_type=%s',sql.split()[0],type(error).__name__)
            raise
    def conversations(self, search=''):
        return self.db.execute('SELECT * FROM conversations WHERE title LIKE ? ORDER BY id DESC',('%'+search+'%',)).fetchall()
    def create(self,title=tr('گفت‌وگوی جدید'),provider='deepseek'):
        return self.execute('INSERT INTO conversations(title,provider) VALUES(?,?)',(title,provider)).lastrowid
    def messages(self,cid):
        return self.db.execute('SELECT * FROM messages WHERE conversation_id=? ORDER BY id',(cid,)).fetchall()
    def messages_page(self,cid,before=None,limit=50):
        if before is None:
            rows=self.db.execute('SELECT * FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?',(cid,limit)).fetchall()
        else:
            rows=self.db.execute('SELECT * FROM messages WHERE conversation_id=? AND id<? ORDER BY id DESC LIMIT ?',(cid,before,limit)).fetchall()
        return list(reversed(rows))
    def latest_message(self,cid,role=None):
        if role:
            return self.db.execute('SELECT * FROM messages WHERE conversation_id=? AND role=? ORDER BY id DESC LIMIT 1',(cid,role)).fetchone()
        return self.db.execute('SELECT * FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT 1',(cid,)).fetchone()
    def add(self,cid,role,content,status='sent'):
        mid=self.execute('INSERT INTO messages(conversation_id,role,content,status) VALUES(?,?,?,?)',(cid,role,content,status)).lastrowid
        logging.getLogger('deepseek_desktop.backend').info('message_committed conversation_local_id=%s message_local_id=%s role=%s status=%s',cid,mid,role,status)
        return mid
    def update_message(self,mid,content=None,status=None):
        if content is not None and status is not None: self.execute('UPDATE messages SET content=?,status=? WHERE id=?',(content,status,mid))
        elif content is not None: self.execute('UPDATE messages SET content=? WHERE id=?',(content,mid))
        elif status is not None: self.execute('UPDATE messages SET status=? WHERE id=?',(status,mid))
    def acknowledge_response(self,cid,user_id,message_id):
        with self.db:
            if user_id: self.db.execute("UPDATE messages SET status='sent' WHERE id=?",(user_id,))
            self.db.execute('UPDATE conversations SET parent_id=?,pending_id=? WHERE id=?',(str(message_id),str(message_id),cid))
    def recover_interrupted(self):
        self.execute("UPDATE messages SET status='interrupted' WHERE status IN ('pending','streaming')")
    def set_project(self,cid,root=None,mode=None,files=None):
        if root is not None: self.execute('UPDATE conversations SET project_root=? WHERE id=?',(root or None,cid))
        if mode is not None: self.execute('UPDATE conversations SET project_mode=? WHERE id=?',(1 if mode else 0,cid))
        if files is not None: self.execute('UPDATE conversations SET project_files=? WHERE id=?',(json.dumps(list(files),ensure_ascii=False),cid))
    def project(self,cid):
        row=self.db.execute('SELECT project_root,project_mode,project_files FROM conversations WHERE id=?',(cid,)).fetchone() if cid else None
        if not row: return None,False,[]
        try: files=json.loads(row['project_files'] or '[]')
        except ValueError: files=[]
        return row['project_root'],bool(row['project_mode']),files
    def settings(self):
        defaults=dict(theme='Light',thinking=False,search=False,streaming=True,auto_continue=True,font=12,timeout=60,provider='deepseek',qwen_model='qwen3.7-plus',qwen_transport='browser',qwen_inline_code=True,language='system')
        for row in self.db.execute('SELECT * FROM settings'):
            try: defaults[row['key']]=json.loads(row['value'])
            except (ValueError,TypeError): pass
        return defaults
    def save_settings(self,values):
        for k,v in values.items(): self.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(k,json.dumps(v)))
