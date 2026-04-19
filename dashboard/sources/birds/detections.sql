SELECT
    CURRENT_TIMESTAMP::TIMESTAMP AS detected_at,
    ''::VARCHAR                  AS file_path,
    ''::VARCHAR                  AS common_name,
    ''::VARCHAR                  AS scientific_name,
    0.0::FLOAT                   AS confidence,
    0.0::FLOAT                   AS lat,
    0.0::FLOAT                   AS lon
WHERE 1 = 0
