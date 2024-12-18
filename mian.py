import logging
from typing import List
import asyncio
import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

# Токены
BOT_TOKEN = "7005471990:AAHhK1u7Y9AcmEhTgwKCknjQTo5T_x8XTLQ"
ACCUWEATHER_API_KEY = "8A96qkJwssWWikSzA9HwBL4qj7Y7I20V"

# Логируем
logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ОПределяем состояний
class WeatherFlow(StatesGroup):
    input_start = State()
    input_end = State()
    input_midpoints = State()
    choose_forecast = State()

# Получение ключа местоположения
async def fetch_location_key(city: str) -> str:
    endpoint = "http://dataservice.accuweather.com/locations/v1/cities/search"
    params = {"apikey": ACCUWEATHER_API_KEY, "q": city, "language": "ru"}
    async with aiohttp.ClientSession() as session:
        async with session.get(endpoint, params=params) as response:
            if response.status != 200:
                logging.error(f"Ошибка при запросе ключа для {city}: {response.status}")
                return None
            data = await response.json()
            return data[0]["Key"] if data else None

# Лут прогноза погоды
async def fetch_weather_forecast(location_key: str) -> list:
    forecast_url = f"http://dataservice.accuweather.com/forecasts/v1/daily/5day/{location_key}"
    params = {"apikey": ACCUWEATHER_API_KEY, "metric": "true", "language": "ru"}
    async with aiohttp.ClientSession() as session:
        async with session.get(forecast_url, params=params) as response:
            if response.status != 200:
                logging.error(f"Ошибка при получении прогноза - {location_key}: {response.status}")
                return []
            data = await response.json()
            return data.get("DailyForecasts", [])


# Прогноз городов
async def generate_forecast(cities: List[str], days: int):
    forecasts = []
    for city in cities:
        loc_key = await fetch_location_key(city)
        if not loc_key:
            forecasts.append({"location": city, "forecast": "Данные недоступны"})
            continue

        forecast_data = await fetch_weather_forecast(loc_key)
        forecast_data = forecast_data[:days]

        city_forecast = []
        for entry in forecast_data:
            date = entry["Date"].split("T")[0]
            temp_range = f"{entry['Temperature']['Minimum']['Value']} - {entry['Temperature']['Maximum']['Value']} °C"
            conditions = entry["Day"]["IconPhrase"]
            city_forecast.append({"date": date, "temperature": temp_range, "conditions": conditions})

        forecasts.append({"location": city, "forecast": city_forecast})
    return forecasts

# ОФормление
def display_forecast(forecast_data):
    result = ""
    for city_data in forecast_data:
        result += f"Прогноз для {city_data['location']}:\n"
        if city_data['forecast'] == "Данные недоступны":
            result += " Нельзя получить данные для этого города.\n\n"
        else:
            for day in city_data['forecast']:
                result += f"{day['date']}: {day['temperature']}, {day['conditions']}\n"
        result += "\n"
    return result


@dp.message(Command("start"))
async def handle_start(message: Message):
    await message.answer("Привет! Я бот, который даёт прогноз погоды для городов. \n"
                         "Напиши /help, чтобы узнать больше информации обо мне.")

@dp.message(Command("help"))
async def handle_help(message: Message):
    await message.answer("Команды:\n/start - приветственное сообщение для начало работы"
                         "\n/help - справка"
                         "\n/weather - прогноз погоды")

@dp.message(Command("weather"))
async def handle_weather(message: Message, state: FSMContext):
    await message.answer("Введите начальный город:")
    await state.set_state(WeatherFlow.input_start)

@dp.message(WeatherFlow.input_start)
async def receive_start_city(message: Message, state: FSMContext):
    await state.update_data(start_city=message.text)
    await message.answer("Введите конечный город:")
    await state.set_state(WeatherFlow.input_end)

@dp.message(WeatherFlow.input_end)
async def receive_end_city(message: Message, state: FSMContext):
    await state.update_data(end_city=message.text)
    builder = InlineKeyboardBuilder()
    builder.button(text="Промежуточные точки", callback_data="add_midpoints")
    builder.button(text="Не хочу", callback_data="skip_midpoints")
    await message.answer("Хотите добавить промежуточные города?", reply_markup=builder.as_markup())
    await state.set_state(WeatherFlow.input_midpoints)

@dp.callback_query(WeatherFlow.input_midpoints, lambda call: call.data == "add_midpoints")
async def handle_add_midpoints(call: CallbackQuery):
    await call.message.answer("Введите промежуточные города через запятую (Novosibirsk, Kazan):")
    await call.answer()

@dp.callback_query(WeatherFlow.input_midpoints, lambda call: call.data == "skip_midpoints")
async def handle_skip_midpoints(call: CallbackQuery, state: FSMContext):
    await state.update_data(midpoints=[])
    await call.message.answer("Вы возжелали построить маршрут без промежуточных точек.")
    await call.answer()
    await request_forecast_interval(call.message, state)

@dp.message(WeatherFlow.input_midpoints)
async def receive_midpoints(message: Message, state: FSMContext):
    midpoints = [city.strip() for city in message.text.split(",") if city.strip()]
    await state.update_data(midpoints=midpoints)
    await request_forecast_interval(message, state)

async def request_forecast_interval(msg: Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="3 дня", callback_data="3_days")
    builder.button(text="5 дней", callback_data="5_days")
    await msg.answer("Выберите интервал для прогноза:", reply_markup=builder.as_markup())
    await state.set_state(WeatherFlow.choose_forecast)

@dp.callback_query(WeatherFlow.choose_forecast, lambda call: call.data in {"3_days", "5_days"})
async def handle_forecast_choice(call: CallbackQuery, state: FSMContext):
    days = 3 if call.data == "3_days" else 5
    await state.update_data(days=days)

    user_data = await state.get_data()
    cities = [user_data["start_city"]] + user_data.get("midpoints", []) + [user_data["end_city"]]
    try:
        forecasts = await generate_forecast(cities, days)
        await call.message.answer(display_forecast(forecasts))
    except Exception as e:
        logging.exception("Ошибка при обработке прогноза")
        await call.message.answer("Произошла ошибка. Попробуйте снова позже.")
    await state.clear()

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
