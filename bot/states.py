from aiogram.fsm.state import State, StatesGroup


class GenImage(StatesGroup):
    waiting_prompt = State()


class EditPhoto(StatesGroup):
    waiting_photo = State()


class StyleTransfer(StatesGroup):
    waiting_photo = State()


class RemoveBG(StatesGroup):
    waiting_photo = State()


class Upscale(StatesGroup):
    waiting_photo = State()


class GenVideo(StatesGroup):
    waiting_prompt = State()


class ImgToVideo(StatesGroup):
    waiting_photo = State()


class PromoRedeem(StatesGroup):
    waiting_code = State()


# Admin
class AdminBroadcast(StatesGroup):
    waiting_text = State()


class AdminUser(StatesGroup):
    waiting_id = State()


class AdminGrant(StatesGroup):
    waiting_id = State()
    waiting_amount = State()


class AdminBan(StatesGroup):
    waiting_id = State()


class AdminPromo(StatesGroup):
    waiting_code = State()
    waiting_stars = State()
    waiting_uses = State()
