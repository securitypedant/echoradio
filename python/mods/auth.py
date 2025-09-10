import json
import bcrypt

from flask import render_template, session, redirect, url_for, flash, request, current_app
from functools import wraps

from mods.logger import logger

def auth():
    if request.method == 'POST':
        admin_password = request.form.get('admin_password')

        if admin_password and check_admin_password(admin_password):
            session['logged_in'] = True
            return redirect(url_for('home'))

        flash('Invalid password', 'danger')

    return render_template('auth.html')


def check_admin_password(password):
    # Replace with your actual password checking logic
    with open(current_app.config['SERVER_CONFIG_FILE']) as f:
        config = json.load(f)

    stored_hash = config.get("admin_password")
    if not stored_hash:
        return False

    return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))

def logout():
    session.pop('logged_in', None)
    logger.info(f"Admin logged out successfully.")
    flash('Logged out successfully', 'success')
    return redirect(url_for('home'))

def login():
    if request.method == 'POST':
        admin_password = request.form.get('admin_password')

        if admin_password and check_admin_password(admin_password):
            session['logged_in'] = True
            logger.info(f"Admin logged in successfully.")
            return redirect(url_for('home'))

        flash('Invalid password', 'danger')

    return render_template('auth.html')

def auth_required():
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Only enforce auth if enable_admin is True
            if current_app.config.get("ENABLE_ADMIN", False):
                if 'logged_in' not in session:
                    return redirect(url_for('auth'))

            return f(*args, **kwargs)
        return decorated_function
    return decorator