# 2차 시도

데이터프레임: [Steam Market and Product Metadata](https://www.kaggle.com/datasets/mahdiheidarpoor/steam-market-and-product-metadata-935-games)
<br />

**작업환경**

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Jupyter](https://img.shields.io/badge/Jupyter-%23F37626.svg?style=for-the-badge&logo=jupyter&logoColor=white)
![Pandas](https://img.shields.io/badge/Pandas-150458?style=for-the-badge&logo=pandas&logoColor=white)

<br />

**결과**
<br />
전처리 성공.
<br />
결측치 제거. 이상치 미제거: 실제 압도적으로 긍정/부정적 평가를 받았을 가능성이 있음. 또한 긍정평가, 부정평가의 수치가 백분율이므로 분석에 있어서 문제가 되지 않으리라 판단.
<br />
장르의 경우, 하나의 행에 여러 장르가 포함되어 있으므로, 장르 테이블을 별도로 분리하여 각 행 당 하나의 장르만 포함되도록 처리.
<br /><br />
**유저 평가 테이블**
<br />
컬럼: app_id, name, release_date, price_usd, review_score_pct, total_reviews, estimated_owners, steam_developer, review_score_negative
<br />
**게임 장르 테이블**
<br />
컬럼: app_id, name, steam_official_genres
