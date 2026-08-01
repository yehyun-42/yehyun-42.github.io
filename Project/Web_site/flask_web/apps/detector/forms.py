from flask_wtf.file import FileAllowed, FileField, FileRequired
from flask_wtf.form import FlaskForm
from wtforms.fields.simple import SubmitField

class UploadImageForm(FlaskForm):
    image=FileField(
        validators=[
            FileRequired("이미지 파일을 지정해 주세요."),
            FileAllowed(["png","jpg","jpeg"], "지원되지 않는 이미지 형식입니다."),
        ]
    )
    submit=SubmitField("업로드")

class DatectorForm(FlaskForm):
    submit=SubmitField("감지")

class DeleteForm(FlaskForm):
    submit=SubmitField("삭제")

    
class Live_streamForm(FlaskForm):
    submit = SubmitField("실시간 영상 감지")