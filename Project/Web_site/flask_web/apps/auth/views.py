from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for
)

from apps.app import db
from apps.auth.forms import SignUpForm, LoginForm
from apps.auth.models import User
from flask_login import login_user, logout_user

auth=Blueprint("auth",
               __name__,
               template_folder="templates",
               static_folder="static"
               )

@auth.route("/")
def index():
    return render_template("auth/index.html")

@auth.route("/signup", methods=["GET", "POST"])
def signup():
    form=SignUpForm()
    if form.validate_on_submit():
        user=User(
            username=form.username.data,
            email=form.email.data,
            password=form.password.data,
        )

        if user.is_duplicate_email():
            flash("이미 등록된 이메일입니다.")
            return redirect(url_for("auth.signup"))
        
        db.session.add(user)
        db.session.commit()

        return redirect(url_for("auth.login"))

    return render_template("auth/signup.html", form=form)

@auth.route("/login", methods=["GET", "POST"])
def login():
    form=LoginForm()
    if form.validate_on_submit():
        user=User.query.filter_by(email=form.email.data).first()

        if user is not None and user.verify_password(form.password.data):
            login_user(user)
            return redirect(url_for("detector.index"))
        
        flash("메일 주소 또는 비밀번호가 일치하지 않습니다.")
    return render_template("auth/login.html", form=form)

@auth.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("detector.index"))
