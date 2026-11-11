# q1: inventario ligero (sin precios). Solo lectura.
psq -tc "select column_name, data_type from information_schema.columns where table_schema='core' and table_name='player_availability_obs' order by ordinal_position" 
echo "--- obs por origen/estado"
psq -tc "select origin, status, count(*), min(observed_at), max(observed_at) from core.player_availability_obs group by 1,2 order by 1,2"
echo "--- obs absence_type"
psq -tc "select absence_type, count(*) from core.player_availability_obs group by 1 order by 2 desc limit 10"
echo "--- evidence typed player"
psq -tc "select origin, subject_type, claim_type, count(*), sum((fixture_id is null)::int) as nofix, min(retrieved_at), max(retrieved_at) from ai.evidence where subject_type is not null group by 1,2,3 order by 1,2,3"
echo "--- evidence provider kinds"
psq -tc "select origin, kind, count(*), min(retrieved_at), max(retrieved_at), sum((provider_player_id is null)::int) from ai.evidence where subject_type is null group by 1,2 order by 1,2"
echo "--- fixtures cols"
psq -tc "select column_name from information_schema.columns where table_schema='core' and table_name='fixtures' order by ordinal_position" | tr '\n' ' '
echo; echo "--- teams cols"
psq -tc "select column_name from information_schema.columns where table_schema='core' and table_name='teams' order by ordinal_position" | tr '\n' ' '
echo; echo "--- competitions cols"
psq -tc "select column_name from information_schema.columns where table_schema='core' and table_name in ('competitions','competition_seasons') order by table_name, ordinal_position" | tr '\n' ' '
echo; echo "--- consensus indexes"
psq -tc "select indexname, indexdef from pg_indexes where schemaname='market' and tablename like 'market_consensus%' limit 10"
