"""FSM-состояния для кнопок, которым нужен свободный текст следующим сообщением
(Ask/Search) — сама команда запускается кнопкой, а не вводом /ask <вопрос>."""

from aiogram.fsm.state import State, StatesGroup


class MenuState(StatesGroup):
    waiting_for_ask = State()
    waiting_for_search = State()
