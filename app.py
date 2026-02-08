import eventlet
eventlet.monkey_patch() 

from flask import Flask, render_template_string, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret_key_123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///olympiad.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, async_mode='eventlet')
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'index'

# === БАЗА ДАННЫХ ===
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True)
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(128))
    rating = db.Column(db.Integer, default=1000)
    wins = db.Column(db.Integer, default=0)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.Text)
    answer = db.Column(db.String(200))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# === ДИЗАЙН ===
STYLE = """
<style>
    body { font-family: 'Segoe UI', sans-serif; background: #eef2f3; margin: 0; padding: 20px; }
    .container { max-width: 800px; margin: 0 auto; }
    .card { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); margin-bottom: 20px; }
    h1, h2 { color: #333; }
    input { width: 100%; padding: 12px; margin: 8px 0; border: 1px solid #ddd; border-radius: 6px; box-sizing: border-box; }
    button { width: 100%; padding: 12px; background: #667eea; color: white; border: none; border-radius: 6px; font-size: 16px; cursor: pointer; transition: 0.3s; }
    button:hover { background: #5a6fd6; }
    .btn-red { background: #e35d5b; } .btn-red:hover { background: #d64543; }
    .nav { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
    .hidden { display: none; }
    .stat-box { display: flex; gap: 15px; margin-bottom: 15px; }
    .stat-item { background: #f8f9fa; padding: 10px; border-radius: 8px; flex: 1; text-align: center; }
</style>
"""

HTML_LOGIN = """
<html><head><title>Вход</title>""" + STYLE + """</head><body>
<div class="container">
    <div class="card">
        <h2 style="text-align:center;">🏆 Олимпиада Вход</h2>
        <form method="POST">
            <input type="text" name="username" placeholder="Ваше имя" required>
            <input type="email" name="email" placeholder="Email" required>
            <input type="password" name="password" placeholder="Пароль" required>
            <div style="display:flex; gap:10px; margin-top:10px;">
                <button type="submit" name="action" value="login">Войти</button>
                <button type="submit" name="action" value="register" style="background:#28a745;">Регистрация</button>
            </div>
        </form>
        <p style="color:red; text-align:center;">{{ msg }}</p>
    </div>
</div>
</body></html>
"""

HTML_DASHBOARD = """
<html><head><title>Кабинет</title>""" + STYLE + """
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
</head><body>
<div class="container">
    <div class="nav">
        <h3>👤 {{ current_user.username }}</h3>
        <a href="/logout"><button class="btn-red" style="width:auto; padding: 8px 15px;">Выход</button></a>
    </div>

    <!-- Статистика -->
    <div class="stat-box">
        <div class="stat-item">⭐ Рейтинг: <b>{{ current_user.rating }}</b></div>
        <div class="stat-item">🏆 Побед: <b>{{ current_user.wins }}</b></div>
    </div>

    <!-- Генератор -->
    <div class="card">
        <h3>🤖 Тренировка с ИИ</h3>
        <p id="ai_text" style="font-style:italic; color:#555;">Нажми кнопку для генерации задачи...</p>
        <button onclick="genTask()" style="background:#17a2b8;">Сгенерировать задачу</button>
    </div>

    <!-- PvP Арена -->
    <div class="card" id="pvp_area">
        <h3>⚔️ PvP Дуэль (Онлайн)</h3>
        <div id="lobby">
            <p>Нажмите "Поиск", чтобы найти соперника.</p>
            <button onclick="findMatch()" id="btnFind">🔍 Найти соперника</button>
            <p id="status" style="color:#666; margin-top:10px;"></p>
        </div>
        
        <div id="game" class="hidden">
            <h2 style="color:#667eea;">ВОПРОС:</h2>
            <p id="q_text" style="font-size:18px; font-weight:bold;"></p>
            <input type="text" id="ans" placeholder="Ваш ответ...">
            <button onclick="sendAns()" style="margin-top:10px;">Отправить ответ</button>
        </div>
    </div>
</div>

<script>
    const socket = io();
    let roomID = null;
    let taskID = null;

    // Генерация задачи (фейк ИИ)
    async function genTask() {
        document.getElementById('ai_text').innerText = "Думаю...";
        let res = await fetch('/generate');
        let data = await res.json();
        document.getElementById('ai_text').innerText = data.text;
    }

    // PvP Логика
    function findMatch() {
        document.getElementById('btnFind').disabled = true;
        document.getElementById('status').innerText = "⏳ Поиск соперника... (Откройте вторую вкладку)";
        socket.emit('find_match');
    }

    socket.on('match_start', (data) => {
        document.getElementById('lobby').classList.add('hidden');
        document.getElementById('game').classList.remove('hidden');
        document.getElementById('q_text').innerText = data.question;
        roomID = data.room;
        taskID = data.task_id;
    });

    socket.on('game_over', (data) => {
        alert(data.msg);
        location.reload(); 
    });

    function sendAns() {
        let val = document.getElementById('ans').value;
        socket.emit('check_answer', {room: roomID, task_id: taskID, answer: val});
    }
</script>
</body></html>
"""

# === СЕРВЕРНАЯ ЧАСТЬ ===
@app.route('/', methods=['GET', 'POST'])
def index():
    if current_user.is_authenticated:
        return render_template_string(HTML_DASHBOARD)
    
    msg = ""
    if request.method == 'POST':
        u = request.form.get('username')
        e = request.form.get('email')
        p = request.form.get('password')
        act = request.form.get('action')
        
        if act == 'register':
            if User.query.filter_by(email=e).first():
                msg = "Такой Email уже есть!"
            else:
                user = User(username=u, email=e, password_hash=generate_password_hash(p))
                db.session.add(user)
                db.session.commit()
                login_user(user)
                return redirect('/')
        else:
            user = User.query.filter_by(email=e).first()
            if user and check_password_hash(user.password_hash, p):
                login_user(user)
                return redirect('/')
            else:
                msg = "Ошибка входа"
    return render_template_string(HTML_LOGIN, msg=msg)

@app.route('/logout')
def logout():
    logout_user()
    return redirect('/')

@app.route('/generate')
def generate():
    t = Task.query.order_by(db.func.random()).first()
    return jsonify({'text': f"Задача: {t.question}"})

# === PVP SOCKETS ===
queue = []

@socketio.on('find_match')
def on_find():
    uid = current_user.id
    if uid not in queue:
        queue.append(uid)
    
    if len(queue) >= 2:
        p1 = queue.pop(0)
        p2 = queue.pop(0)
        room = f"room_{p1}_{p2}"
        
        join_room(room) 
        
        t = Task.query.order_by(db.func.random()).first()
        socketio.emit('match_start', {'room': room, 'question': t.question, 'task_id': t.id})

@socketio.on('check_answer')
def on_check(data):
    task = Task.query.get(data['task_id'])
    if task.answer.lower().strip() == data['answer'].lower().strip():
        current_user.wins += 1
        current_user.rating += 25
        db.session.commit()
        socketio.emit('game_over', {'msg': f"🏆 Победил {current_user.username}!\nПравильный ответ: {task.answer}"})

# === ЗАПУСК ===
def init_data():
    db.create_all()
    if not Task.query.first():
        tasks = [
            ("2 + 2 * 2", "6"), ("Столица Франции", "Париж"), ("5 * 5", "25"), 
            ("H2O это", "Вода"), ("Корень из 100", "10"), ("3 в квадрате", "9"),
            ("Сколько бит в байте", "8"), ("Язык этого сайта", "Python"),
            ("Первый месяц года", "Январь"), ("Планета Земля по счету от Солнца", "3"),
            ("100 / 4", "25"), ("Сколько ног у паука", "8"), ("Автор 'Войны и мир'", "Толстой"),
            ("Самое глубокое озеро", "Байкал"), ("1 час = ... минут", "60"),
            ("Красный + Желтый =", "Оранжевый"), ("Столица России", "Москва"),
            ("Число Пи (примерно)", "3.14"), ("Количество материков", "6"), ("50% от 200", "100")
        ]
        for q, a in tasks:
            db.session.add(Task(question=q, answer=a))
        db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        init_data()
    socketio.run(app, debug=True, port=5000, host='0.0.0.0')
