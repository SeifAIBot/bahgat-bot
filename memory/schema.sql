PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS members (
  user_id INTEGER PRIMARY KEY,
  username TEXT,
  first_name TEXT,
  notes TEXT DEFAULT '',
  mood INTEGER DEFAULT 30,
  grudge TEXT DEFAULT '',
  updated_at REAL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER,
  user_id INTEGER,
  role TEXT,
  text TEXT,
  created_at REAL
);
CREATE TABLE IF NOT EXISTS processed_updates (
  update_id INTEGER PRIMARY KEY,
  chat_id INTEGER,
  received_at REAL
);
CREATE TABLE IF NOT EXISTS provider_usage (
  provider TEXT,
  date TEXT,
  requests INTEGER DEFAULT 0,
  tokens_in INTEGER DEFAULT 0,
  tokens_out INTEGER DEFAULT 0,
  exhausted_until REAL,
  PRIMARY KEY(provider, date)
);
CREATE TABLE IF NOT EXISTS pinned_facts (
  user_id INTEGER,
  fact TEXT,
  created_at REAL,
  PRIMARY KEY(user_id, fact)
);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  update_id INTEGER,
  chat_id INTEGER,
  payload TEXT,
  status TEXT DEFAULT 'pending',
  retry_after REAL DEFAULT 0,
  created_at REAL
);
CREATE TABLE IF NOT EXISTS daily_usage (
  user_id INTEGER,
  chat_id INTEGER,
  date TEXT,
  count INTEGER DEFAULT 0,
  PRIMARY KEY(user_id, chat_id, date)
);
CREATE TABLE IF NOT EXISTS bot_state (
  key TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE IF NOT EXISTS youtube_files (
  url TEXT,
  audio_only INTEGER,
  file_id TEXT,
  size_bytes INTEGER,
  created_at REAL,
  PRIMARY KEY(url, audio_only)
);
CREATE TABLE IF NOT EXISTS response_cache (
  normalised_text TEXT,
  intent TEXT,
  mood_bucket TEXT,
  reply TEXT,
  created_at REAL,
  PRIMARY KEY(normalised_text, intent, mood_bucket)
);
CREATE TABLE IF NOT EXISTS hourly_usage (
  user_id INTEGER,
  chat_id INTEGER,
  hour TEXT,
  count INTEGER DEFAULT 0,
  PRIMARY KEY(user_id, chat_id, hour)
);
CREATE INDEX IF NOT EXISTS idx_processed_updates_received ON processed_updates(received_at);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id);
