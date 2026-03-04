from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime, timedelta
import random
import string
import os

# Flask App erstellen
app = Flask(__name__)
app.config['SECRET_KEY'] = 'dein-geheimes-passwort-hier'
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'keys.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Datenbank initialisieren
db = SQLAlchemy(app)

# Login Manager für Passwortschutz
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ============================================
# DATENBANK MODELLE
# ============================================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)

class Key(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key_value = db.Column(db.String(64), unique=True, nullable=False)
    duration = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    deactivated_at = db.Column(db.DateTime, nullable=True)
    deactivation_reason = db.Column(db.String(50), nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    is_deleted = db.Column(db.Boolean, default=False)
    
    def time_remaining(self):
        if self.is_deleted:
            return "Deleted"
        if not self.is_active:
            if self.deactivation_reason == 'expired':
                return "Expired"
            elif self.deactivation_reason == 'manual':
                return "Manually deactivated"
            else:
                return "Deactivated"
        
        remaining = self.expires_at - datetime.utcnow()
        if remaining.total_seconds() <= 0:
            self.is_active = False
            self.deactivation_reason = 'expired'
            self.deactivated_at = datetime.utcnow()
            db.session.commit()
            return "Expired"
        
        days = remaining.days
        hours = remaining.seconds // 3600
        minutes = (remaining.seconds % 3600) // 60
        
        if days > 0:
            return f"{days} days {hours} hrs"
        elif hours > 0:
            return f"{hours} hrs {minutes} min"
        else:
            return f"{minutes} minutes"
    
    def get_status_text(self):
        if self.is_deleted:
            return "🗑️ Deleted"
        if self.is_active:
            return "✅ Active"
        elif self.deactivation_reason == 'expired':
            return "⏰ Expired"
        elif self.deactivation_reason == 'manual':
            return "👤 Manually deactivated"
        else:
            return "❌ Inactive"

# ============================================
# KEY GENERIERUNG
# ============================================

def generate_key():
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    key = ''.join(random.choice(chars) for _ in range(32))
    formatted = '-'.join([key[i:i+8] for i in range(0, 32, 8)])
    return formatted

def get_expiry_date(duration):
    now = datetime.utcnow()
    if duration == "1 day":
        return now + timedelta(days=1)
    elif duration == "3 days":
        return now + timedelta(days=3)
    elif duration == "7 days":
        return now + timedelta(days=7)
    elif duration == "30 days":
        return now + timedelta(days=30)
    elif duration == "Lifetime":
        return now + timedelta(days=365*100)
    return now + timedelta(days=1)

# ============================================
# LOGIN FUNKTIONEN
# ============================================

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def create_default_user():
    if not User.query.filter_by(username='admin').first():
        user = User(username='admin', password='geheim123')
        db.session.add(user)
        db.session.commit()
        print("✅ User 'admin' created")

# ============================================
# ROUTEN
# ============================================

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Wrong username or password')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    expired_keys = Key.query.filter(
        Key.expires_at < datetime.utcnow(),
        Key.is_active == True,
        Key.is_deleted == False
    ).all()
    
    for key in expired_keys:
        key.is_active = False
        key.deactivation_reason = 'expired'
        key.deactivated_at = datetime.utcnow()
    
    db.session.commit()
    
    active_keys = Key.query.filter_by(is_active=True, is_deleted=False).order_by(Key.created_at.desc()).all()
    deactivated_keys = Key.query.filter_by(is_active=False, is_deleted=False).order_by(Key.created_at.desc()).all()
    deleted_keys = Key.query.filter_by(is_deleted=True).order_by(Key.deleted_at.desc()).all()
    
    return render_template('dashboard.html', 
                         active_keys=active_keys, 
                         deactivated_keys=deactivated_keys,
                         deleted_keys=deleted_keys,
                         now=datetime.utcnow)

@app.route('/generate_key/<duration>')
@login_required
def generate_key_route(duration):
    new_key = Key(
        key_value=generate_key(),
        duration=duration,
        expires_at=get_expiry_date(duration),
        is_active=True
    )
    
    db.session.add(new_key)
    db.session.commit()
    
    flash(f'✅ New {duration} key generated!')
    return redirect(url_for('dashboard'))

@app.route('/deactivate_key/<int:key_id>', methods=['POST'])
@login_required
def deactivate_key(key_id):
    key = Key.query.get_or_404(key_id)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'requires_confirmation': True, 'key': key.key_value[:15] + '...'})
    
    key.is_active = False
    key.deactivation_reason = 'manual'
    key.deactivated_at = datetime.utcnow()
    db.session.commit()
    
    flash(f'🔴 Key {key.key_value[:15]}... was deactivated')
    return redirect(url_for('dashboard'))

@app.route('/confirm_deactivate/<int:key_id>')
@login_required
def confirm_deactivate(key_id):
    key = Key.query.get_or_404(key_id)
    key.is_active = False
    key.deactivation_reason = 'manual'
    key.deactivated_at = datetime.utcnow()
    db.session.commit()
    
    flash(f'🔴 Key {key.key_value[:15]}... was deactivated')
    return redirect(url_for('dashboard'))

@app.route('/delete_key/<int:key_id>')
@login_required
def delete_key(key_id):
    key = Key.query.get_or_404(key_id)
    key.is_active = False
    key.is_deleted = True
    key.deleted_at = datetime.utcnow()
    db.session.commit()
    
    flash(f'🗑️ Key {key.key_value[:15]}... moved to Bin')
    return redirect(url_for('dashboard'))

@app.route('/restore_key/<int:key_id>')
@login_required
def restore_key(key_id):
    key = Key.query.get_or_404(key_id)
    
    if key.deactivated_at or key.deleted_at:
        if key.deactivated_at:
            pause_start = key.deactivated_at
        else:
            pause_start = key.deleted_at
        
        pause_duration = datetime.utcnow() - pause_start
        key.expires_at = key.expires_at + pause_duration
    
    if key.expires_at > datetime.utcnow():
        key.is_active = True
        key.is_deleted = False
        key.deleted_at = None
        key.deactivation_reason = 'reactivated'
        flash(f'✅ Key {key.key_value[:15]}... was restored! (Timer paused)')
    else:
        key.is_active = False
        key.is_deleted = False
        key.deleted_at = None
        flash(f'⚠️ Key {key.key_value[:15]}... restored (expired)')
    
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/clear_bin')
@login_required
def clear_bin():
    deleted_keys = Key.query.filter_by(is_deleted=True).all()
    count = len(deleted_keys)
    
    for key in deleted_keys:
        db.session.delete(key)
    
    db.session.commit()
    
    flash(f'🗑️ {count} keys permanently deleted')
    return redirect(url_for('dashboard'))

@app.route('/reactivate_key/<int:key_id>')
@login_required
def reactivate_key(key_id):
    key = Key.query.get_or_404(key_id)
    
    if key.deactivated_at:
        pause_duration = datetime.utcnow() - key.deactivated_at
        key.expires_at = key.expires_at + pause_duration
    
    if key.expires_at > datetime.utcnow():
        key.is_active = True
        key.deactivation_reason = 'reactivated'
        key.deactivated_at = None
        flash(f'✅ Key {key.key_value[:15]}... was reactivated! (Timer paused)')
    else:
        flash(f'❌ Cannot reactivate - expired even with pause!')
    
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/search_keys')
@login_required
def search_keys():
    query = request.args.get('q', '').strip()
    tab = request.args.get('tab', 'active')
    
    if not query:
        if tab == 'active':
            keys = Key.query.filter_by(is_active=True, is_deleted=False).order_by(Key.created_at.desc()).all()
        elif tab == 'deactivated':
            keys = Key.query.filter_by(is_active=False, is_deleted=False).order_by(Key.created_at.desc()).all()
        else:
            keys = Key.query.filter_by(is_deleted=True).order_by(Key.deleted_at.desc()).all()
    else:
        if tab == 'active':
            keys = Key.query.filter_by(is_active=True, is_deleted=False, key_value=query).all()
        elif tab == 'deactivated':
            keys = Key.query.filter_by(is_active=False, is_deleted=False, key_value=query).all()
        else:
            keys = Key.query.filter_by(is_deleted=True, key_value=query).all()
    
    return render_template('key_results.html', 
                         keys=keys, 
                         tab=tab, 
                         query=query,
                         now=datetime.utcnow)

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        old = request.form.get('old_password')
        new = request.form.get('new_password')
        confirm = request.form.get('confirm_password')
        
        if current_user.password != old:
            flash('❌ Old password is wrong')
        elif new != confirm:
            flash('❌ New passwords do not match')
        elif len(new) < 4:
            flash('❌ Password must be at least 4 characters')
        else:
            current_user.password = new
            db.session.commit()
            flash('✅ Password changed successfully!')
            return redirect(url_for('dashboard'))
    
    return render_template('change_password.html')

@app.route('/api/keys')
@login_required
def api_keys():
    active_keys = Key.query.filter_by(is_active=True, is_deleted=False).order_by(Key.created_at.desc()).all()
    deactivated_keys = Key.query.filter_by(is_active=False, is_deleted=False).order_by(Key.created_at.desc()).all()
    deleted_keys = Key.query.filter_by(is_deleted=True).order_by(Key.deleted_at.desc()).all()
    
    return jsonify({
        'active': [{
            'id': k.id,
            'key_value': k.key_value,
            'duration': k.duration,
            'created_at': k.created_at.strftime('%d.%m.%Y %H:%M'),
            'time_remaining': k.time_remaining(),
            'status': '✅ Active'
        } for k in active_keys],
        'deactivated': [{
            'id': k.id,
            'key_value': k.key_value,
            'duration': k.duration,
            'created_at': k.created_at.strftime('%d.%m.%Y %H:%M'),
            'deactivated_at': k.deactivated_at.strftime('%d.%m.%Y %H:%M') if k.deactivated_at else '-',
            'status': k.get_status_text()
        } for k in deactivated_keys],
        'deleted': [{
            'id': k.id,
            'key_value': k.key_value,
            'duration': k.duration,
            'created_at': k.created_at.strftime('%d.%m.%Y %H:%M'),
            'deleted_at': k.deleted_at.strftime('%d.%m.%Y %H:%M') if k.deleted_at else '-',
            'status': '🗑️ Deleted'
        } for k in deleted_keys]
    })

# ============================================
# APP STARTEN
# ============================================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_default_user()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)