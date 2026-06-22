"""ORM-модели базы данных."""
import config
from sqlalchemy import Column, Integer, String, Boolean
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session

# Инициализация подключения
engine = create_engine(config.db_url, echo=False)
session = scoped_session(sessionmaker(bind=engine, autoflush=False))
Base = declarative_base()


class User(Base):
    __tablename__ = 'bot_user'
    user_id = Column(String, primary_key=True)
    user_name = Column(String)
    language = Column(String)

    def __init__(self, user_id, user_name, language):
        self.user_id = user_id
        self.user_name = user_name
        self.language = language


class DrawProgress(Base):
    """Розыгрыш в процессе создания (черновик)."""
    __tablename__ = 'draw_progress'
    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    chanel_id = Column(String)
    chanel_name = Column(String)
    text = Column(String)
    file_type = Column(String)
    file_id = Column(String)
    winers_count = Column(Integer)
    post_time = Column(String)
    end_time = Column(String)

    def __init__(self, user_id, chanel_id, chanel_name, text, file_type, file_id,
                 winers_count, post_time, end_time):
        self.user_id = str(user_id)
        self.chanel_id = str(chanel_id)
        self.chanel_name = chanel_name
        self.text = text
        self.file_type = file_type
        self.file_id = file_id
        self.winers_count = winers_count
        self.post_time = post_time
        self.end_time = end_time


class DrawNot(Base):
    """Розыгрыш ожидающий публикации."""
    __tablename__ = 'notposted'
    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    chanel_id = Column(String)
    chanel_name = Column(String)
    text = Column(String)
    file_type = Column(String)
    file_id = Column(String)
    winers_count = Column(Integer)
    post_time = Column(String)
    end_time = Column(String)

    def __init__(self, id, user_id, chanel_id, chanel_name, text, file_type,
                 file_id, winers_count, post_time, end_time):
        self.id = id
        self.user_id = str(user_id)
        self.chanel_id = str(chanel_id)
        self.chanel_name = chanel_name
        self.text = text
        self.file_type = file_type
        self.file_id = file_id
        self.winers_count = winers_count
        self.post_time = post_time
        self.end_time = end_time


class Draw(Base):
    """Активный опубликованный розыгрыш."""
    __tablename__ = 'draw_'
    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    message_id = Column(String)
    chanel_id = Column(String)
    chanel_name = Column(String)
    text = Column(String)
    file_type = Column(String)
    file_id = Column(String)
    winers_count = Column(Integer)
    post_time = Column(String)
    end_time = Column(String)

    def __init__(self, id, user_id, message_id, chanel_id, chanel_name, text,
                 file_type, file_id, winers_count, post_time, end_time):
        self.id = id
        self.user_id = str(user_id)
        self.message_id = str(message_id)
        self.chanel_id = str(chanel_id)
        self.chanel_name = chanel_name
        self.text = text
        self.file_type = file_type
        self.file_id = file_id
        self.winers_count = winers_count
        self.post_time = post_time
        self.end_time = end_time


class SubscribeChannel(Base):
    """Канал для проверки подписки."""
    __tablename__ = 'channel'
    id = Column(Integer, primary_key=True)
    draw_id = Column(Integer)
    user_id = Column(String)
    channel_id = Column(String)

    def __init__(self, draw_id, user_id, channel_id):
        self.draw_id = draw_id
        self.user_id = user_id
        self.channel_id = channel_id


class DrawPlayer(Base):
    """Участник розыгрыша."""
    __tablename__ = 'players'
    id = Column(Integer, primary_key=True)
    draw_id = Column(Integer)
    user_id = Column(String)
    user_name = Column(String)
    is_rigged = Column(Boolean, default=False, nullable=False)

    def __init__(self, draw_id, user_id, user_name, is_rigged=False):
        self.draw_id = draw_id
        self.user_id = user_id
        self.user_name = user_name
        self.is_rigged = is_rigged


class Admin(Base):
    """Администратор бота (имеет доступ к подкрутке всех розыгрышей)."""
    __tablename__ = 'admins'
    id = Column(Integer, primary_key=True)
    user_id = Column(String, unique=True, nullable=False)
    user_name = Column(String)
    added_by = Column(String)  # кто добавил

    def __init__(self, user_id, user_name=None, added_by=None):
        self.user_id = str(user_id)
        self.user_name = user_name
        self.added_by = added_by


class State(Base):
    """Состояние FSM пользователя."""
    __tablename__ = 'user_state'
    user_id = Column(Integer, primary_key=True)
    state = Column(String)
    arg = Column(String)

    def __init__(self, user_id, state, arg=None):
        self.user_id = user_id
        self.state = state
        self.arg = arg
