from flask import Flask, render_template, request, redirect, flash, url_for, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import random

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///trading_competition.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'some-secret-key'  # Change for production
db = SQLAlchemy(app)

# ----- Database Models -----

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    balance = db.Column(db.Float, default=10000.0)

class Trade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ticker = db.Column(db.String(10), nullable=False)
    trade_type = db.Column(db.String(4), nullable=False)  # "buy" or "sell"
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class TickerPrice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticker = db.Column(db.String(10), unique=True, nullable=False)
    price = db.Column(db.Float, nullable=False)

# ----- Utility Functions -----

def get_current_user():
    """Return the logged-in User object, or None if no user is logged in."""
    user_id = session.get('user_id')
    if user_id:
        return User.query.get(user_id)
    return None

def get_stock_price():
    """Return the current price of 'AA', or initialize to 100.0 if not found."""
    record = TickerPrice.query.filter_by(ticker="AA").first()
    if record:
        return record.price
    else:
        default_price = 100.0
        new_record = TickerPrice(ticker="AA", price=default_price)
        db.session.add(new_record)
        db.session.commit()
        return default_price

def randomly_fluctuate_price():
    """Apply a small random fluctuation (±0.5%) to the price of 'AA'."""
    record = TickerPrice.query.filter_by(ticker="AA").first()
    if record:
        fluctuation_percentage = random.uniform(-0.005, 0.005)
        record.price = max(0.01, record.price * (1 + fluctuation_percentage))
        db.session.commit()

def calculate_portfolio(user_id):
    """
    Portfolio = user's cash + net shares * current price.
    """
    user = User.query.get(user_id)
    if not user:
        return 0.0

    trades = Trade.query.filter_by(user_id=user_id, ticker="AA").order_by(Trade.timestamp.asc()).all()
    net_qty = 0
    for trade in trades:
        if trade.trade_type == "buy":
            net_qty += trade.quantity
        else:
            net_qty -= trade.quantity

    current_price = get_stock_price()
    return user.balance + net_qty * current_price

def compute_open_positions(user_id):
    """
    Calculate net position, avg cost, unrealized PnL for 'AA' for the given user.
    If net_qty = 0, return an empty list.
    """
    trades = Trade.query.filter_by(user_id=user_id, ticker="AA").all()
    total_buy_qty = 0
    total_sell_qty = 0
    total_buy_value = 0.0
    total_sell_value = 0.0

    for t in trades:
        if t.trade_type == "buy":
            total_buy_qty += t.quantity
            total_buy_value += t.quantity * t.price
        else:
            total_sell_qty += t.quantity
            total_sell_value += t.quantity * t.price

    net_qty = total_buy_qty - total_sell_qty
    if net_qty == 0:
        return []

    current_price = get_stock_price()
    if net_qty > 0:
        avg_cost = (total_buy_value - total_sell_value) / net_qty
        unrealized_pnl = net_qty * (current_price - avg_cost)
    else:
        avg_cost = (total_sell_value - total_buy_value) / abs(net_qty)
        unrealized_pnl = abs(net_qty) * (avg_cost - current_price)

    return [{
        'ticker': "AA",
        'net_qty': net_qty,
        'avg_cost': avg_cost,
        'current_price': current_price,
        'unrealized_pnl': unrealized_pnl
    }]

# ----- Routes -----

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash("Username already taken.")
            return redirect(url_for('register'))

        # Hash the password
        password_hash = generate_password_hash(password)
        new_user = User(username=username, password_hash=password_hash, balance=10000.0)
        db.session.add(new_user)
        db.session.commit()
        flash("Registration successful! Please log in.")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            flash("Logged in successfully.")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid username or password.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash("Logged out.")
    return redirect(url_for('index'))

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    current_user = get_current_user()
    if not current_user:
        flash("Please log in to access the dashboard.")
        return redirect(url_for('login'))

    message = None

    if request.method == 'POST':
        # "action" is either "buy" or "sell"
        trade_type = request.form['action']
        try:
            quantity = int(request.form['quantity'])
        except ValueError:
            flash("Quantity must be an integer.")
            return redirect(url_for('dashboard'))

        current_price = get_stock_price()
        total_cost = current_price * quantity

        if trade_type == "buy":
            if current_user.balance < total_cost:
                flash("Insufficient balance for this trade.")
            else:
                current_user.balance -= total_cost
                new_trade = Trade(
                    user_id=current_user.id,
                    ticker="AA",
                    trade_type="buy",
                    quantity=quantity,
                    price=current_price
                )
                db.session.add(new_trade)
                db.session.commit()
                message = f"Buy order executed: {quantity} shares of AA at ${current_price:.2f}"

        elif trade_type == "sell":
            # For a real app, you'd check net holdings to prevent overselling.
            current_user.balance += total_cost
            new_trade = Trade(
                user_id=current_user.id,
                ticker="AA",
                trade_type="sell",
                quantity=quantity,
                price=current_price
            )
            db.session.add(new_trade)
            db.session.commit()
            message = f"Sell order executed: {quantity} shares of AA at ${current_price:.2f}"

    portfolio_value = calculate_portfolio(current_user.id)
    trades = Trade.query.filter_by(user_id=current_user.id, ticker="AA").order_by(Trade.timestamp.desc()).all()
    open_positions = compute_open_positions(current_user.id)

    return render_template(
        'dashboard.html',
        user=current_user,
        trades=trades,
        message=message,
        portfolio_value=portfolio_value,
        open_positions=open_positions,
        current_price=get_stock_price()
    )

@app.route('/leaderboard')
def leaderboard():
    # Show all users by descending portfolio value
    users = User.query.all()
    leaderboard_data = []
    for u in users:
        value = calculate_portfolio(u.id)
        leaderboard_data.append({
            'username': u.username,
            'portfolio': value
        })
    leaderboard_data.sort(key=lambda x: x['portfolio'], reverse=True)
    return render_template('leaderboard.html', leaderboard=leaderboard_data)

# Called by client-side JS every second to fluctuate and return the new price
@app.route('/ticker_prices')
def ticker_prices_endpoint():
    randomly_fluctuate_price()
    record = TickerPrice.query.filter_by(ticker="AA").first()
    if record:
        return jsonify({'prices': [{'ticker': record.ticker, 'price': record.price}]})
    return jsonify({'prices': []})

@app.route('/open_positions')
def open_positions_endpoint():
    """Returns open positions for the logged-in user as JSON."""
    current_user = get_current_user()
    if not current_user:
        return jsonify({'positions': []})
    positions = compute_open_positions(current_user.id)
    return jsonify({'positions': positions})

# ----- Main Runner -----
if __name__ == '__main__':
    db.drop_all()
    db.create_all()

    # Initialize Ticker "AA" at $100 if not exists
    if not TickerPrice.query.filter_by(ticker="AA").first():
        db.session.add(TickerPrice(ticker="AA", price=100.0))
    db.session.commit()

    app.run(debug=True)
