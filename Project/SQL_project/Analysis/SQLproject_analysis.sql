select distinct steam_official_genres
from genres_table;

select name, steam_official_genres
from genres_table
where steam_official_genres='nan';

delete
from genres_table
where name='Eternal Return' or name='Riichi City Date A Live';

delete
from game_table
where name='Eternal Return' or name='Riichi City Date A Live';

select g.name
from game_table g, genres_table n
where g.app_id=n.app_id and n.steam_official_genres='nan';

commit;

select n.steam_official_genres, avg(g.review_score_pct) as positive
from game_table g, genres_table n
where g.app_id=n.app_id
group by n.steam_official_genres
order by positive desc;

select g.name, n.steam_official_genres, g.review_score_pct
from game_table g, genres_table n
where g.app_id=n.app_id and n.steam_official_genres='Indie'
order by g.review_score_pct desc limit 10;

select g.name, n.steam_official_genres, 
	dense_rank() over(order by n.steam_official_genres desc) as genres_rank, 
    g.review_score_pct
from game_table g, genres_table n
where g.app_id=n.app_id;

select g.name, n.steam_official_genres, (
	select row_number() over(partition by steam_official_genres order by review_score_pct desc) 
    from game_table g, genres_table n limit 1
    ) as genres_rank
from game_table g, genres_table n;

select * from (
	select g.name, n.steam_official_genres, g.review_score_pct,
		row_number() over (partition by n.steam_official_genres 
					order by g.review_score_pct desc) as genres_rank
                    from game_table g, genres_table n
                    where g.app_id=n.app_id
) as rankrow
where rankrow.review_score_pct >=95
order by rankrow.steam_official_genres asc;

select g.name, g.review_score_pct, n.steam_official_genres
from game_table g, genres_table n
where g.app_id=n.app_id and g.review_score_pct >= 95
order by g.review_score_pct desc;

select name, release_date, estimated_owners
from game_table
order by estimated_owners asc limit 10;

select name, price_usd, estimated_owners
from game_table
order by price_usd desc limit 10;

select name, price_usd, estimated_owners
from game_table
order by price_usd asc limit 10;

select name, price_usd, estimated_owners
from game_table
order by estimated_owners desc limit 10;

select name, price_usd, estimated_owners
from game_table
order by estimated_owners asc limit 10;

select n.steam_official_genres,
	sum(g.estimated_owners) as total_owners, 
	avg(g.estimated_owners) as avg_owners
from game_table g, genres_table n
where g.app_id=n.app_id
group by n.steam_official_genres
order by total_owners desc;

select steam_developer, 
	avg(estimated_owners) as avg_owners, 
    avg(review_score_pct) as avg_positive
from game_table
group by steam_developer
order by steam_developer asc;