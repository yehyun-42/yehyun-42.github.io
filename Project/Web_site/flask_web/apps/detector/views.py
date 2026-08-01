from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for
)

from flask import current_app, send_from_directory
import uuid
from pathlib import Path
from apps.detector.forms import UploadImageForm, DeleteForm, Live_streamForm
from flask_login import current_user, login_required

from apps.detector.models import UserImage, UserImageTag
from apps.app import db
from apps.auth.models import User

from sqlalchemy.exc import SQLAlchemyError

dt=Blueprint(
    "detector",
    __name__,
    template_folder="templates"
)

@dt.route("/")
def index():
    user_images=(
        db.session.query(User, UserImage)
        .join(UserImage)
        .filter(User.id==UserImage.user_id)
        .all()
    )

    delete_form=DeleteForm()

    return render_template("detector/index.html", 
                           user_images=user_images, 
                           delete_form=delete_form)

@dt.route("/images/<path:filename>")
def image_file(filename):
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)

@dt.route("/upload", methods=["GET", "POST"])
@login_required
def upload_image():
    form=UploadImageForm()
    if form.validate_on_submit():
        file=form.image.data

        ext=Path(file.filename).suffix
        image_uuid_file_name=str(uuid.uuid4()) + ext

        image_path=Path(
            current_app.config["UPLOAD_FOLDER"], image_uuid_file_name
        )
        file.save(image_path)

        user_image=UserImage(
            user_id=current_user.id, image_path=image_uuid_file_name
        )
        db.session.add(user_image)
        db.session.commit()

        return redirect(url_for("detector.index"))
    return render_template("detector/upload.html", form=form)

@dt.route("/images/delete/<string:image_id>", methods=["POST"])
@login_required
def delete_image(image_id):
    try:
        db.session.query(UserImageTag).filter(
            UserImageTag.user_image_id==image_id
        ).delete()
        db.session.query(UserImage).filter(UserImage.id==image_id).delete()

        db.session.commit()

    except SQLAlchemyError as e:
        flash("이미지 삭제 처리에서 오류가 발생했습니다.")

        current_app.logger.error(e)
        db.session.rollback()

    return redirect(url_for("detector.index"))

@dt.route("/live_stream")
@login_required
def live_stream():
    form=Live_streamForm()
    return render_template("detector/live_stream.html", form=form)