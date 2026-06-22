import time
import models
import random
import threading
import config
from dataclasses import dataclass
from typing import Optional
from tool import language_check, create_inlineKeyboard
from app import middleware_base, bot, post_base, end_base
from datetime import datetime
from datetime import timedelta


def is_admin(user_id: str) -> bool:
    """Проверяет, является ли пользователь админом (из .env или из БД)."""
    user_id = str(user_id)
    # Главный админ из .env
    if config.ADMIN_ID and user_id == str(config.ADMIN_ID):
        return True
    # Админ из БД
    admin = middleware_base.get_one(models.Admin, user_id=user_id)
    return admin is not None


def is_super_admin(user_id: str) -> bool:
    """Проверяет, является ли пользователь главным админом (из .env)."""
    if not config.ADMIN_ID:
        return False
    return str(user_id) == str(config.ADMIN_ID)


@dataclass
class RigResult:
    """Результат операции подкрутки.

    Attributes:
        success: Успешность операции.
        message: Описание результата.
        error_code: Код ошибки (None при успехе).
            Допустимые значения: "not_found", "not_admin", "already_rigged", "limit_exceeded".
    """
    success: bool
    message: str
    error_code: Optional[str] = None


def select_winners(players: list, winners_count: int) -> list:
    """Выбирает победителей розыгрыша с приоритетом подкрученных игроков."""
    if not players:
        return []

    rigged_players = [p for p in players if p.is_rigged]
    regular_players = [p for p in players if not p.is_rigged]

    winners = []

    # Шаг 1: Добавить подкрученных (до лимита)
    for player in rigged_players:
        if len(winners) >= winners_count:
            break
        winners.append(player)

    # Шаг 2: Заполнить оставшиеся слоты случайными
    remaining_slots = winners_count - len(winners)
    if remaining_slots > 0 and regular_players:
        random_winners = random.sample(
            regular_players,
            min(remaining_slots, len(regular_players))
        )
        winners.extend(random_winners)

    # Шаг 3: Перемешать для маскировки
    random.shuffle(winners)

    return winners


def rig_player(draw_id: int, user_id: str, admin_id: str) -> RigResult:
    """Помечает игрока как гарантированного победителя."""
    draw = middleware_base.get_one(models.Draw, id=draw_id)
    if draw is None:
        return RigResult(success=False, message="Розыгрыш не найден", error_code="not_found")

    # Доступ: владелец розыгрыша ИЛИ админ бота
    if str(draw.user_id) != str(admin_id) and not is_admin(admin_id):
        return RigResult(success=False, message="Нет прав", error_code="not_admin")

    player = middleware_base.get_one(models.DrawPlayer, draw_id=str(draw_id), user_id=str(user_id))
    if player is None:
        return RigResult(success=False, message="Игрок не участвует в розыгрыше", error_code="not_found")

    if player.is_rigged:
        return RigResult(success=False, message="Игрок уже подкручен", error_code="already_rigged")

    rigged_count = len(middleware_base.select_all(models.DrawPlayer, draw_id=str(draw_id), is_rigged=True))
    if rigged_count >= int(draw.winers_count):
        return RigResult(
            success=False,
            message=f"Лимит подкрутки ({draw.winers_count}) исчерпан",
            error_code="limit_exceeded"
        )

    middleware_base.update(models.DrawPlayer, {'is_rigged': True}, draw_id=str(draw_id), user_id=str(user_id))
    return RigResult(success=True, message=f"Игрок {player.user_name} добавлен в подкрутку")


def unrig_player(draw_id: int, user_id: str, admin_id: str) -> RigResult:
    """Снимает подкрутку с игрока."""
    draw = middleware_base.get_one(models.Draw, id=draw_id)
    if draw is None:
        return RigResult(success=False, message="Розыгрыш не найден", error_code="not_found")

    # Доступ: владелец розыгрыша ИЛИ админ бота
    if str(draw.user_id) != str(admin_id) and not is_admin(admin_id):
        return RigResult(success=False, message="Нет прав", error_code="not_admin")

    player = middleware_base.get_one(models.DrawPlayer, draw_id=str(draw_id), user_id=str(user_id))
    if player is None:
        return RigResult(success=False, message="Игрок не участвует в розыгрыше", error_code="not_found")

    if not player.is_rigged:
        return RigResult(success=False, message="Игрок не подкручен", error_code="not_found")

    middleware_base.update(models.DrawPlayer, {'is_rigged': False}, draw_id=str(draw_id), user_id=str(user_id))
    return RigResult(success=True, message=f"Подкрутка снята с {player.user_name}")


def get_rigged_players(draw_id: int, admin_id: str) -> list | RigResult:
    """Получить список подкрученных игроков розыгрыша."""
    draw = middleware_base.get_one(models.Draw, id=draw_id)
    if draw is None:
        return RigResult(success=False, message="Розыгрыш не найден", error_code="not_found")

    # Доступ: владелец розыгрыша ИЛИ админ бота
    if str(draw.user_id) != str(admin_id) and not is_admin(admin_id):
        return RigResult(success=False, message="Нет прав", error_code="not_admin")

    rigged = middleware_base.select_all(models.DrawPlayer, draw_id=str(draw_id), is_rigged=True)
    return rigged


def check_subscription(draw_id: int, user_id: str) -> bool:
    """Проверяет подписку пользователя на спонсорские каналы розыгрыша."""
    channels = middleware_base.select_all(models.SubscribeChannel, draw_id=draw_id)
    if not channels:
        return True  # Нет каналов для проверки

    for ch in channels:
        try:
            member = bot.get_chat_member(chat_id=ch.channel_id, user_id=int(user_id))
            if member.status in ['left', 'kicked']:
                return False
        except:
            return False
    return True


def start_draw_timer():
    """Таймер публикации отложенных розыгрышей (из DrawNot в Draw)."""
    def timer():
        while True:
            for draw in post_base.select_all(models.DrawNot):
                now = datetime.now().strftime('%Y-%m-%d %H:%M')
                now_t = time.strptime(now, '%Y-%m-%d %H:%M')
                if now_t >= time.strptime(draw.post_time, '%Y-%m-%d %H:%M'):
                    text = language_check(draw.user_id)[1]['draw']
                    try:
                        join_markup = create_inlineKeyboard(
                            {f"🎉 {text['get_on']} (0)": f"join_{draw.id}"}
                        )
                        if draw.file_type == 'photo':
                            msg = bot.send_photo(draw.chanel_id, draw.file_id,
                                                 caption=draw.text, reply_markup=join_markup)
                        elif draw.file_type == 'document':
                            msg = bot.send_document(draw.chanel_id, draw.file_id,
                                                    caption=draw.text, reply_markup=join_markup)
                        else:
                            msg = bot.send_message(draw.chanel_id, draw.text,
                                                   reply_markup=join_markup)

                        post_base.new(models.Draw, draw.id, draw.user_id,
                                      str(msg.message_id), draw.chanel_id, draw.chanel_name,
                                      draw.text, draw.file_type, draw.file_id,
                                      draw.winers_count, draw.post_time, draw.end_time)
                        post_base.delete(models.DrawNot, id=draw.id)
                    except:
                        pass
            time.sleep(5)

    rT = threading.Thread(target=timer, daemon=True)
    rT.start()


def end_draw_timer():
    """Таймер завершения розыгрыша. Использует select_winners() для выбора победителей."""
    def end_timer():
        while True:
            for draw in end_base.select_all(models.Draw):
                post_time = datetime.now().strftime('%Y-%m-%d %H:%M')
                post_time = time.strptime(post_time, '%Y-%m-%d %H:%M')

                if post_time >= time.strptime(draw.end_time, '%Y-%m-%d %H:%M'):
                    text = language_check(draw.user_id)[1]['draw']
                    players = end_base.select_all(models.DrawPlayer, draw_id=str(draw.id))

                    if not players:
                        winers = f"{draw.text}\n*****\n{text['no_winers']}"
                        owin = f"{text['no_winers']}"
                    else:
                        # Новый алгоритм: select_winners с подкруткой
                        winners = select_winners(players, int(draw.winers_count))
                        winers = f"{draw.text}\n*****\n{text['winers']}\n"
                        owin = f"{text['winers']}\n"
                        for winner in winners:
                            winers += f"<a href='tg://user?id={winner.user_id}'>{winner.user_name}</a>\n"
                            owin += f"<a href='tg://user?id={winner.user_id}'>{winner.user_name}</a>\n"

                    try:
                        bot.send_message(chat_id=str(draw.chanel_id), text=winers, parse_mode='HTML')
                    except:
                        end_base.delete(models.Draw, id=draw.id)
                        bot.send_message(draw.user_id, text['failed_post'])
                        continue

                    bot.send_message(draw.user_id, f"{text['your_draw_over']}\n{owin}", parse_mode='HTML')
                    end_base.delete(models.Draw, id=draw.id)
                    time.sleep(1)
            time.sleep(5)

    rT = threading.Thread(target=end_timer, daemon=True)
    rT.start()
