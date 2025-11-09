--
-- PostgreSQL database dump
--

\restrict pqchlHNTG8b5gASfLjnETgdQUzb7CtwDJH2M7oQZpLh0d7aJctDcASTWjqpV4QT

-- Dumped from database version 16.10 (Ubuntu 16.10-1.pgdg24.04+1)
-- Dumped by pg_dump version 16.10 (Ubuntu 16.10-1.pgdg24.04+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pump; Type: SCHEMA; Schema: -; Owner: elcrypto
--

CREATE SCHEMA pump;


ALTER SCHEMA pump OWNER TO elcrypto;

--
-- Name: SCHEMA pump; Type: COMMENT; Schema: -; Owner: elcrypto
--

COMMENT ON SCHEMA pump IS 'Pump Detection System - схема для хранения данных о сигналах и пампах';


--
-- Name: calculate_confidence_score(bigint); Type: FUNCTION; Schema: pump; Owner: elcrypto
--

CREATE FUNCTION pump.calculate_confidence_score(p_signal_id bigint) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_signal pump.signals%ROWTYPE;
    v_confirmations_count INTEGER;
    v_score INTEGER := 0;
    v_volume_score INTEGER := 0;
    v_oi_score INTEGER := 0;
    v_spot_score INTEGER := 0;
    v_confirmation_score INTEGER := 0;
    v_timing_score INTEGER := 0;
    v_hours_since NUMERIC;
BEGIN
    -- Получаем сигнал
    SELECT * INTO v_signal FROM pump.signals WHERE id = p_signal_id;

    IF NOT FOUND THEN
        RETURN 0;
    END IF;

    -- 1. Volume Score (0-25)
    IF v_signal.futures_spike_ratio_7d >= 5.0 THEN
        v_volume_score := 25;
    ELSIF v_signal.futures_spike_ratio_7d >= 3.0 THEN
        v_volume_score := 20;
    ELSIF v_signal.futures_spike_ratio_7d >= 2.0 THEN
        v_volume_score := 15;
    ELSE
        v_volume_score := 10;
    END IF;

    -- 2. OI Score (0-25)
    IF v_signal.oi_change_pct >= 50 THEN
        v_oi_score := 25;
    ELSIF v_signal.oi_change_pct >= 30 THEN
        v_oi_score := 20;
    ELSIF v_signal.oi_change_pct >= 15 THEN
        v_oi_score := 15;
    ELSIF v_signal.oi_change_pct >= 5 THEN
        v_oi_score := 10;
    END IF;

    -- 3. Spot Sync Score (0-20)
    IF v_signal.has_spot_sync AND v_signal.spot_spike_ratio_7d >= 2.0 THEN
        v_spot_score := 20;
    ELSIF v_signal.has_spot_sync AND v_signal.spot_spike_ratio_7d >= 1.5 THEN
        v_spot_score := 10;
    END IF;

    -- 4. Confirmation Score (0-20)
    SELECT COUNT(*) INTO v_confirmations_count
    FROM pump.signal_confirmations
    WHERE signal_id = p_signal_id;

    v_confirmation_score := LEAST(20, v_confirmations_count * 5);

    -- 5. Timing Score (0-10)
    v_hours_since := EXTRACT(EPOCH FROM (NOW() - v_signal.detected_at)) / 3600;

    IF v_hours_since <= 4 THEN
        v_timing_score := 10;
    ELSIF v_hours_since <= 12 THEN
        v_timing_score := 7;
    ELSIF v_hours_since <= 24 THEN
        v_timing_score := 5;
    ELSIF v_hours_since <= 48 THEN
        v_timing_score := 3;
    END IF;

    -- Суммарный скор
    v_score := v_volume_score + v_oi_score + v_spot_score + v_confirmation_score + v_timing_score;

    -- Обновляем таблицу scores
    INSERT INTO pump.signal_scores (
        signal_id,
        volume_score,
        oi_score,
        spot_sync_score,
        confirmation_score,
        timing_score,
        total_score,
        confidence_level
    ) VALUES (
        p_signal_id,
        v_volume_score,
        v_oi_score,
        v_spot_score,
        v_confirmation_score,
        v_timing_score,
        v_score,
        CASE
            WHEN v_score >= 80 THEN 'EXTREME'
            WHEN v_score >= 60 THEN 'HIGH'
            WHEN v_score >= 40 THEN 'MEDIUM'
            ELSE 'LOW'
        END
    )
    ON CONFLICT (signal_id) DO UPDATE SET
        volume_score = EXCLUDED.volume_score,
        oi_score = EXCLUDED.oi_score,
        spot_sync_score = EXCLUDED.spot_sync_score,
        confirmation_score = EXCLUDED.confirmation_score,
        timing_score = EXCLUDED.timing_score,
        total_score = EXCLUDED.total_score,
        confidence_level = EXCLUDED.confidence_level,
        updated_at = NOW();

    RETURN v_score;
END;
$$;


ALTER FUNCTION pump.calculate_confidence_score(p_signal_id bigint) OWNER TO elcrypto;

--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: pump; Owner: elcrypto
--

CREATE FUNCTION pump.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION pump.update_updated_at_column() OWNER TO elcrypto;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: signal_scores; Type: TABLE; Schema: pump; Owner: elcrypto
--

CREATE TABLE pump.signal_scores (
    signal_id bigint NOT NULL,
    volume_score integer DEFAULT 0,
    oi_score integer DEFAULT 0,
    spot_sync_score integer DEFAULT 0,
    confirmation_score integer DEFAULT 0,
    timing_score integer DEFAULT 0,
    total_score integer DEFAULT 0,
    confidence_level character varying(20),
    max_price_increase numeric(10,2),
    time_to_pump_hours integer,
    pump_strength character varying(20),
    validated boolean DEFAULT false,
    validation_timestamp timestamp with time zone,
    score_details jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT signal_scores_confidence_level_check CHECK (((confidence_level)::text = ANY ((ARRAY['EXTREME'::character varying, 'HIGH'::character varying, 'MEDIUM'::character varying, 'LOW'::character varying])::text[]))),
    CONSTRAINT signal_scores_confirmation_score_check CHECK (((confirmation_score >= 0) AND (confirmation_score <= 20))),
    CONSTRAINT signal_scores_oi_score_check CHECK (((oi_score >= 0) AND (oi_score <= 25))),
    CONSTRAINT signal_scores_spot_sync_score_check CHECK (((spot_sync_score >= 0) AND (spot_sync_score <= 20))),
    CONSTRAINT signal_scores_timing_score_check CHECK (((timing_score >= 0) AND (timing_score <= 10))),
    CONSTRAINT signal_scores_total_score_check CHECK (((total_score >= 0) AND (total_score <= 100))),
    CONSTRAINT signal_scores_volume_score_check CHECK (((volume_score >= 0) AND (volume_score <= 25)))
);


ALTER TABLE pump.signal_scores OWNER TO elcrypto;

--
-- Name: TABLE signal_scores; Type: COMMENT; Schema: pump; Owner: elcrypto
--

COMMENT ON TABLE pump.signal_scores IS 'Детальная оценка и скоринг сигналов';


--
-- Name: signal_tracking; Type: TABLE; Schema: pump; Owner: elcrypto
--

CREATE TABLE pump.signal_tracking (
    id bigint NOT NULL,
    signal_id bigint NOT NULL,
    tracking_timestamp timestamp with time zone DEFAULT now() NOT NULL,
    price numeric(20,8) NOT NULL,
    price_change_pct numeric(10,2),
    price_change_24h numeric(10,2),
    volume_24h numeric(20,2),
    volume_ratio_vs_baseline numeric(10,2),
    buy_sell_ratio numeric(10,2),
    oi_total numeric(20,2),
    oi_change_pct numeric(10,2),
    oi_change_24h numeric(10,2),
    liquidations_24h_long numeric(20,2),
    liquidations_24h_short numeric(20,2),
    current_confidence integer,
    status character varying(20),
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT signal_tracking_current_confidence_check CHECK (((current_confidence >= 0) AND (current_confidence <= 100)))
);


ALTER TABLE pump.signal_tracking OWNER TO elcrypto;

--
-- Name: TABLE signal_tracking; Type: COMMENT; Schema: pump; Owner: elcrypto
--

COMMENT ON TABLE pump.signal_tracking IS 'История изменения метрик сигнала';


--
-- Name: signals; Type: TABLE; Schema: pump; Owner: elcrypto
--

CREATE TABLE pump.signals (
    id bigint NOT NULL,
    trading_pair_id integer NOT NULL,
    pair_symbol character varying(20) NOT NULL,
    detected_at timestamp with time zone DEFAULT now() NOT NULL,
    signal_timestamp timestamp with time zone NOT NULL,
    futures_volume numeric(20,2),
    futures_baseline_7d numeric(20,2),
    futures_baseline_14d numeric(20,2),
    futures_baseline_30d numeric(20,2),
    futures_spike_ratio_7d numeric(10,2) NOT NULL,
    futures_spike_ratio_14d numeric(10,2),
    futures_spike_ratio_30d numeric(10,2),
    spot_volume numeric(20,2),
    spot_baseline_7d numeric(20,2),
    spot_spike_ratio_7d numeric(10,2),
    has_spot_sync boolean DEFAULT false,
    oi_value numeric(20,2),
    oi_change_pct numeric(10,2),
    signal_strength character varying(20) NOT NULL,
    initial_confidence integer DEFAULT 0,
    status character varying(20) DEFAULT 'DETECTED'::character varying,
    is_active boolean DEFAULT true,
    max_price_increase numeric(10,2),
    time_to_pump_hours integer,
    pump_realized boolean DEFAULT false,
    detection_method character varying(50) DEFAULT 'VOLUME_SPIKE'::character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT signals_initial_confidence_check CHECK (((initial_confidence >= 0) AND (initial_confidence <= 100))),
    CONSTRAINT signals_signal_strength_check CHECK (((signal_strength)::text = ANY ((ARRAY['EXTREME'::character varying, 'STRONG'::character varying, 'MEDIUM'::character varying, 'WEAK'::character varying])::text[]))),
    CONSTRAINT signals_status_check CHECK (((status)::text = ANY ((ARRAY['DETECTED'::character varying, 'MONITORING'::character varying, 'CONFIRMED'::character varying, 'FAILED'::character varying, 'EXPIRED'::character varying])::text[])))
);


ALTER TABLE pump.signals OWNER TO elcrypto;

--
-- Name: TABLE signals; Type: COMMENT; Schema: pump; Owner: elcrypto
--

COMMENT ON TABLE pump.signals IS 'Основная таблица обнаруженных сигналов';


--
-- Name: active_signals; Type: VIEW; Schema: pump; Owner: elcrypto
--

CREATE VIEW pump.active_signals AS
 SELECT s.id,
    s.trading_pair_id,
    s.pair_symbol,
    s.detected_at,
    s.signal_timestamp,
    s.futures_volume,
    s.futures_baseline_7d,
    s.futures_baseline_14d,
    s.futures_baseline_30d,
    s.futures_spike_ratio_7d,
    s.futures_spike_ratio_14d,
    s.futures_spike_ratio_30d,
    s.spot_volume,
    s.spot_baseline_7d,
    s.spot_spike_ratio_7d,
    s.has_spot_sync,
    s.oi_value,
    s.oi_change_pct,
    s.signal_strength,
    s.initial_confidence,
    s.status,
    s.is_active,
    s.max_price_increase,
    s.time_to_pump_hours,
    s.pump_realized,
    s.detection_method,
    s.created_at,
    s.updated_at,
    sc.total_score,
    sc.confidence_level,
    t.price_change_pct AS current_price_change
   FROM ((pump.signals s
     LEFT JOIN pump.signal_scores sc ON ((s.id = sc.signal_id)))
     LEFT JOIN LATERAL ( SELECT signal_tracking.price_change_pct
           FROM pump.signal_tracking
          WHERE (signal_tracking.signal_id = s.id)
          ORDER BY signal_tracking.tracking_timestamp DESC
         LIMIT 1) t ON (true))
  WHERE ((s.is_active = true) AND ((s.status)::text = ANY ((ARRAY['DETECTED'::character varying, 'MONITORING'::character varying])::text[])))
  ORDER BY s.detected_at DESC;


ALTER VIEW pump.active_signals OWNER TO elcrypto;

--
-- Name: config; Type: TABLE; Schema: pump; Owner: elcrypto
--

CREATE TABLE pump.config (
    key character varying(100) NOT NULL,
    value text NOT NULL,
    description text,
    value_type character varying(20) DEFAULT 'STRING'::character varying,
    category character varying(50),
    is_active boolean DEFAULT true,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by character varying(100)
);


ALTER TABLE pump.config OWNER TO elcrypto;

--
-- Name: TABLE config; Type: COMMENT; Schema: pump; Owner: elcrypto
--

COMMENT ON TABLE pump.config IS 'Конфигурация системы';


--
-- Name: notifications; Type: TABLE; Schema: pump; Owner: elcrypto
--

CREATE TABLE pump.notifications (
    id bigint NOT NULL,
    signal_id bigint NOT NULL,
    notification_type character varying(50) NOT NULL,
    notification_event character varying(50) NOT NULL,
    recipient character varying(255),
    channel character varying(100),
    confidence_level character varying(20),
    message_text text NOT NULL,
    message_format character varying(20) DEFAULT 'TEXT'::character varying,
    sent_at timestamp with time zone DEFAULT now(),
    is_success boolean DEFAULT true,
    retry_count integer DEFAULT 0,
    error_message text,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT notifications_notification_event_check CHECK (((notification_event)::text = ANY ((ARRAY['NEW_SIGNAL'::character varying, 'CONFIRMATION'::character varying, 'PUMP_STARTED'::character varying, 'TARGET_REACHED'::character varying, 'SIGNAL_WEAKENING'::character varying, 'SIGNAL_FAILED'::character varying, 'EXTREME_CONFIDENCE'::character varying])::text[]))),
    CONSTRAINT notifications_notification_type_check CHECK (((notification_type)::text = ANY ((ARRAY['TELEGRAM'::character varying, 'EMAIL'::character varying, 'WEBHOOK'::character varying, 'SMS'::character varying, 'DISCORD'::character varying])::text[])))
);


ALTER TABLE pump.notifications OWNER TO elcrypto;

--
-- Name: TABLE notifications; Type: COMMENT; Schema: pump; Owner: elcrypto
--

COMMENT ON TABLE pump.notifications IS 'Журнал отправленных уведомлений';


--
-- Name: notifications_id_seq; Type: SEQUENCE; Schema: pump; Owner: elcrypto
--

CREATE SEQUENCE pump.notifications_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE pump.notifications_id_seq OWNER TO elcrypto;

--
-- Name: notifications_id_seq; Type: SEQUENCE OWNED BY; Schema: pump; Owner: elcrypto
--

ALTER SEQUENCE pump.notifications_id_seq OWNED BY pump.notifications.id;


--
-- Name: patterns; Type: TABLE; Schema: pump; Owner: elcrypto
--

CREATE TABLE pump.patterns (
    id integer NOT NULL,
    pattern_name character varying(100) NOT NULL,
    pattern_type character varying(50) NOT NULL,
    description text,
    confidence_boost integer DEFAULT 0,
    conditions jsonb NOT NULL,
    detection_count integer DEFAULT 0,
    success_count integer DEFAULT 0,
    success_rate numeric(5,2),
    avg_pump_size numeric(10,2),
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE pump.patterns OWNER TO elcrypto;

--
-- Name: patterns_id_seq; Type: SEQUENCE; Schema: pump; Owner: elcrypto
--

CREATE SEQUENCE pump.patterns_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE pump.patterns_id_seq OWNER TO elcrypto;

--
-- Name: patterns_id_seq; Type: SEQUENCE OWNED BY; Schema: pump; Owner: elcrypto
--

ALTER SEQUENCE pump.patterns_id_seq OWNED BY pump.patterns.id;


--
-- Name: performance_stats; Type: TABLE; Schema: pump; Owner: elcrypto
--

CREATE TABLE pump.performance_stats (
    id bigint NOT NULL,
    stat_date date DEFAULT CURRENT_DATE NOT NULL,
    stat_hour integer DEFAULT EXTRACT(hour FROM now()),
    signals_detected integer DEFAULT 0,
    signals_confirmed integer DEFAULT 0,
    signals_failed integer DEFAULT 0,
    true_positives integer DEFAULT 0,
    false_positives integer DEFAULT 0,
    accuracy_pct numeric(5,2),
    avg_detection_time_ms integer,
    avg_validation_time_ms integer,
    notifications_sent integer DEFAULT 0,
    notifications_failed integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE pump.performance_stats OWNER TO elcrypto;

--
-- Name: performance_stats_id_seq; Type: SEQUENCE; Schema: pump; Owner: elcrypto
--

CREATE SEQUENCE pump.performance_stats_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE pump.performance_stats_id_seq OWNER TO elcrypto;

--
-- Name: performance_stats_id_seq; Type: SEQUENCE OWNED BY; Schema: pump; Owner: elcrypto
--

ALTER SEQUENCE pump.performance_stats_id_seq OWNED BY pump.performance_stats.id;


--
-- Name: signal_confirmations; Type: TABLE; Schema: pump; Owner: elcrypto
--

CREATE TABLE pump.signal_confirmations (
    id bigint NOT NULL,
    signal_id bigint NOT NULL,
    confirmation_type character varying(50) NOT NULL,
    confirmation_timestamp timestamp with time zone DEFAULT now() NOT NULL,
    metric_value numeric(20,4),
    metric_baseline numeric(20,4),
    metric_ratio numeric(10,2),
    confidence_boost integer DEFAULT 0,
    details jsonb,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT signal_confirmations_confidence_boost_check CHECK (((confidence_boost >= 0) AND (confidence_boost <= 30))),
    CONSTRAINT signal_confirmations_confirmation_type_check CHECK (((confirmation_type)::text = ANY ((ARRAY['VOLUME_SPIKE_REPEAT'::character varying, 'OI_INCREASE'::character varying, 'PRICE_BREAKOUT'::character varying, 'SPOT_SYNC'::character varying, 'FUNDING_RATE_SPIKE'::character varying, 'LARGE_ORDERS'::character varying, 'WHALE_ACTIVITY'::character varying])::text[])))
);


ALTER TABLE pump.signal_confirmations OWNER TO elcrypto;

--
-- Name: TABLE signal_confirmations; Type: COMMENT; Schema: pump; Owner: elcrypto
--

COMMENT ON TABLE pump.signal_confirmations IS 'Подтверждения сигналов различными индикаторами';


--
-- Name: signal_confirmations_id_seq; Type: SEQUENCE; Schema: pump; Owner: elcrypto
--

CREATE SEQUENCE pump.signal_confirmations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE pump.signal_confirmations_id_seq OWNER TO elcrypto;

--
-- Name: signal_confirmations_id_seq; Type: SEQUENCE OWNED BY; Schema: pump; Owner: elcrypto
--

ALTER SEQUENCE pump.signal_confirmations_id_seq OWNED BY pump.signal_confirmations.id;


--
-- Name: signal_tracking_id_seq; Type: SEQUENCE; Schema: pump; Owner: elcrypto
--

CREATE SEQUENCE pump.signal_tracking_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE pump.signal_tracking_id_seq OWNER TO elcrypto;

--
-- Name: signal_tracking_id_seq; Type: SEQUENCE OWNED BY; Schema: pump; Owner: elcrypto
--

ALTER SEQUENCE pump.signal_tracking_id_seq OWNED BY pump.signal_tracking.id;


--
-- Name: signals_id_seq; Type: SEQUENCE; Schema: pump; Owner: elcrypto
--

CREATE SEQUENCE pump.signals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE pump.signals_id_seq OWNER TO elcrypto;

--
-- Name: signals_id_seq; Type: SEQUENCE OWNED BY; Schema: pump; Owner: elcrypto
--

ALTER SEQUENCE pump.signals_id_seq OWNED BY pump.signals.id;


--
-- Name: thresholds; Type: TABLE; Schema: pump; Owner: elcrypto
--

CREATE TABLE pump.thresholds (
    trading_pair_id integer NOT NULL,
    pair_symbol character varying(20) NOT NULL,
    custom_min_spike numeric(10,2),
    custom_extreme_spike numeric(10,2),
    custom_strong_spike numeric(10,2),
    custom_medium_spike numeric(10,2),
    avg_spike_before_pump numeric(10,2),
    avg_days_to_pump numeric(10,2),
    avg_pump_size_pct numeric(10,2),
    total_signals_count integer DEFAULT 0,
    successful_signals_count integer DEFAULT 0,
    historical_accuracy numeric(5,2),
    is_monitored boolean DEFAULT true,
    requires_spot_sync boolean DEFAULT false,
    min_oi_increase_pct numeric(10,2),
    notes text,
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE pump.thresholds OWNER TO elcrypto;

--
-- Name: user_watchlist; Type: TABLE; Schema: pump; Owner: elcrypto
--

CREATE TABLE pump.user_watchlist (
    id bigint NOT NULL,
    user_id character varying(100) NOT NULL,
    trading_pair_id integer,
    pair_symbol character varying(20),
    min_confidence integer DEFAULT 50,
    notification_types text[] DEFAULT ARRAY['NEW_SIGNAL'::text, 'PUMP_STARTED'::text],
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE pump.user_watchlist OWNER TO elcrypto;

--
-- Name: user_watchlist_id_seq; Type: SEQUENCE; Schema: pump; Owner: elcrypto
--

CREATE SEQUENCE pump.user_watchlist_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE pump.user_watchlist_id_seq OWNER TO elcrypto;

--
-- Name: user_watchlist_id_seq; Type: SEQUENCE OWNED BY; Schema: pump; Owner: elcrypto
--

ALTER SEQUENCE pump.user_watchlist_id_seq OWNED BY pump.user_watchlist.id;


--
-- Name: notifications id; Type: DEFAULT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.notifications ALTER COLUMN id SET DEFAULT nextval('pump.notifications_id_seq'::regclass);


--
-- Name: patterns id; Type: DEFAULT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.patterns ALTER COLUMN id SET DEFAULT nextval('pump.patterns_id_seq'::regclass);


--
-- Name: performance_stats id; Type: DEFAULT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.performance_stats ALTER COLUMN id SET DEFAULT nextval('pump.performance_stats_id_seq'::regclass);


--
-- Name: signal_confirmations id; Type: DEFAULT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.signal_confirmations ALTER COLUMN id SET DEFAULT nextval('pump.signal_confirmations_id_seq'::regclass);


--
-- Name: signal_tracking id; Type: DEFAULT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.signal_tracking ALTER COLUMN id SET DEFAULT nextval('pump.signal_tracking_id_seq'::regclass);


--
-- Name: signals id; Type: DEFAULT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.signals ALTER COLUMN id SET DEFAULT nextval('pump.signals_id_seq'::regclass);


--
-- Name: user_watchlist id; Type: DEFAULT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.user_watchlist ALTER COLUMN id SET DEFAULT nextval('pump.user_watchlist_id_seq'::regclass);


--
-- Data for Name: config; Type: TABLE DATA; Schema: pump; Owner: elcrypto
--

COPY pump.config (key, value, description, value_type, category, is_active, updated_at, updated_by) FROM stdin;
min_spike_ratio	1.5	Минимальный spike ratio для детекции	FLOAT	DETECTION	t	2025-11-07 00:23:42.678787+00	\N
extreme_spike_ratio	5.0	Порог для EXTREME сигналов	FLOAT	DETECTION	t	2025-11-07 00:23:42.678787+00	\N
strong_spike_ratio	3.0	Порог для STRONG сигналов	FLOAT	DETECTION	t	2025-11-07 00:23:42.678787+00	\N
medium_spike_ratio	2.0	Порог для MEDIUM сигналов	FLOAT	DETECTION	t	2025-11-07 00:23:42.678787+00	\N
detection_interval_minutes	5	Интервал детекции в минутах	INTEGER	DETECTION	t	2025-11-07 00:23:42.678787+00	\N
detection_lookback_hours	4	Часов назад для поиска аномалий	INTEGER	DETECTION	t	2025-11-07 00:23:42.678787+00	\N
validation_interval_minutes	15	Интервал валидации в минутах	INTEGER	DETECTION	t	2025-11-07 00:23:42.678787+00	\N
monitoring_hours	168	Часов мониторинга после сигнала (7 дней)	INTEGER	DETECTION	t	2025-11-07 00:23:42.678787+00	\N
pump_threshold_pct	10	Процент роста для подтверждения пампа	FLOAT	DETECTION	t	2025-11-07 00:23:42.678787+00	\N
mini_pump_threshold_pct	5	Процент роста для мини-пампа	FLOAT	DETECTION	t	2025-11-07 00:23:42.678787+00	\N
notification_min_confidence	40	Минимальная уверенность для уведомлений	INTEGER	NOTIFICATION	t	2025-11-07 00:23:42.678787+00	\N
telegram_bot_token		Токен Telegram бота	STRING	NOTIFICATION	t	2025-11-07 00:23:42.678787+00	\N
telegram_channel_extreme		Telegram канал для EXTREME сигналов	STRING	NOTIFICATION	t	2025-11-07 00:23:42.678787+00	\N
telegram_channel_high		Telegram канал для HIGH сигналов	STRING	NOTIFICATION	t	2025-11-07 00:23:42.678787+00	\N
telegram_channel_medium		Telegram канал для MEDIUM сигналов	STRING	NOTIFICATION	t	2025-11-07 00:23:42.678787+00	\N
telegram_channel_all		Telegram канал для всех сигналов	STRING	NOTIFICATION	t	2025-11-07 00:23:42.678787+00	\N
confidence_volume_weight	25	Вес volume в расчете уверенности	INTEGER	SCORING	t	2025-11-07 00:23:42.678787+00	\N
confidence_oi_weight	25	Вес OI в расчете уверенности	INTEGER	SCORING	t	2025-11-07 00:23:42.678787+00	\N
confidence_spot_weight	20	Вес spot sync в расчете уверенности	INTEGER	SCORING	t	2025-11-07 00:23:42.678787+00	\N
confidence_confirmation_weight	20	Вес подтверждений в расчете	INTEGER	SCORING	t	2025-11-07 00:23:42.678787+00	\N
confidence_timing_weight	10	Вес времени в расчете	INTEGER	SCORING	t	2025-11-07 00:23:42.678787+00	\N
system_enabled	true	Система включена	BOOLEAN	SYSTEM	t	2025-11-07 00:23:42.678787+00	\N
maintenance_mode	false	Режим обслуживания	BOOLEAN	SYSTEM	t	2025-11-07 00:23:42.678787+00	\N
debug_mode	false	Режим отладки	BOOLEAN	SYSTEM	t	2025-11-07 00:23:42.678787+00	\N
\.


--
-- Data for Name: notifications; Type: TABLE DATA; Schema: pump; Owner: elcrypto
--

COPY pump.notifications (id, signal_id, notification_type, notification_event, recipient, channel, confidence_level, message_text, message_format, sent_at, is_success, retry_count, error_message, created_at) FROM stdin;
\.


--
-- Data for Name: patterns; Type: TABLE DATA; Schema: pump; Owner: elcrypto
--

COPY pump.patterns (id, pattern_name, pattern_type, description, confidence_boost, conditions, detection_count, success_count, success_rate, avg_pump_size, is_active, created_at, updated_at) FROM stdin;
1	extreme_volume_spike	VOLUME	Экстремальный спайк объема >5x	25	{"volume_conditions": {"min_spike_ratio": 5.0}}	0	0	\N	\N	t	2025-11-07 00:23:42.691138+00	2025-11-07 00:23:42.691138+00
2	gradual_accumulation	VOLUME	Постепенный рост объема 3-5 дней	15	{"volume_conditions": {"pattern": "gradual_increase", "duration_days": 3}}	0	0	\N	\N	t	2025-11-07 00:23:42.691138+00	2025-11-07 00:23:42.691138+00
3	spot_futures_sync	COMPOSITE	Синхронный спайк на spot и futures	20	{"spot_sync": true, "min_spot_ratio": 1.5}	0	0	\N	\N	t	2025-11-07 00:23:42.691138+00	2025-11-07 00:23:42.691138+00
4	oi_volume_divergence	COMPOSITE	Рост OI при росте объема	15	{"oi_increase_pct": 10, "volume_spike_ratio": 2.0}	0	0	\N	\N	t	2025-11-07 00:23:42.691138+00	2025-11-07 00:23:42.691138+00
\.


--
-- Data for Name: performance_stats; Type: TABLE DATA; Schema: pump; Owner: elcrypto
--

COPY pump.performance_stats (id, stat_date, stat_hour, signals_detected, signals_confirmed, signals_failed, true_positives, false_positives, accuracy_pct, avg_detection_time_ms, avg_validation_time_ms, notifications_sent, notifications_failed, created_at) FROM stdin;
\.


--
-- Data for Name: signal_confirmations; Type: TABLE DATA; Schema: pump; Owner: elcrypto
--

COPY pump.signal_confirmations (id, signal_id, confirmation_type, confirmation_timestamp, metric_value, metric_baseline, metric_ratio, confidence_boost, details, created_at) FROM stdin;
\.


--
-- Data for Name: signal_scores; Type: TABLE DATA; Schema: pump; Owner: elcrypto
--

COPY pump.signal_scores (signal_id, volume_score, oi_score, spot_sync_score, confirmation_score, timing_score, total_score, confidence_level, max_price_increase, time_to_pump_hours, pump_strength, validated, validation_timestamp, score_details, created_at, updated_at) FROM stdin;
501	25	0	0	0	10	35	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
502	25	0	0	0	10	35	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
503	25	0	0	0	10	35	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
504	25	0	0	0	10	35	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
505	25	0	0	0	10	35	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
506	25	0	0	0	10	35	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
507	25	0	0	0	10	35	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
508	20	0	0	0	10	30	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
509	20	0	0	0	10	30	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
510	20	0	0	0	10	30	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
511	20	0	0	0	10	30	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
512	20	0	0	0	10	30	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
513	20	0	0	0	10	30	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
514	20	0	0	0	10	30	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
515	20	0	0	0	10	30	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
516	20	0	0	0	10	30	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
517	20	0	0	0	10	30	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
518	20	0	0	0	10	30	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
519	20	0	0	0	10	30	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
520	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
521	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
522	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
523	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
524	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
525	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
526	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
527	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
528	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
529	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
530	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
531	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
532	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
533	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
534	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
535	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
536	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
537	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
538	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
539	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
540	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
541	15	0	0	0	10	25	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
542	10	0	0	0	10	20	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
543	10	0	0	0	10	20	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
544	10	0	0	0	10	20	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
545	10	0	0	0	10	20	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
546	10	0	0	0	10	20	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
547	10	0	0	0	10	20	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
548	10	0	0	0	10	20	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
549	10	0	0	0	10	20	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
550	10	0	0	0	10	20	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
551	10	0	0	0	10	20	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:20:01.726533+00	2025-11-07 03:20:01.726533+00
552	10	0	0	0	10	20	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:20:01.726533+00	2025-11-07 03:20:01.726533+00
553	10	0	0	0	10	20	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:20:01.726533+00	2025-11-07 03:20:01.726533+00
554	10	0	0	0	10	20	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:20:01.726533+00	2025-11-07 03:20:01.726533+00
555	10	0	0	0	10	20	LOW	\N	\N	\N	f	\N	\N	2025-11-07 03:20:01.726533+00	2025-11-07 03:20:01.726533+00
\.


--
-- Data for Name: signal_tracking; Type: TABLE DATA; Schema: pump; Owner: elcrypto
--

COPY pump.signal_tracking (id, signal_id, tracking_timestamp, price, price_change_pct, price_change_24h, volume_24h, volume_ratio_vs_baseline, buy_sell_ratio, oi_total, oi_change_pct, oi_change_24h, liquidations_24h_long, liquidations_24h_short, current_confidence, status, created_at) FROM stdin;
\.


--
-- Data for Name: signals; Type: TABLE DATA; Schema: pump; Owner: elcrypto
--

COPY pump.signals (id, trading_pair_id, pair_symbol, detected_at, signal_timestamp, futures_volume, futures_baseline_7d, futures_baseline_14d, futures_baseline_30d, futures_spike_ratio_7d, futures_spike_ratio_14d, futures_spike_ratio_30d, spot_volume, spot_baseline_7d, spot_spike_ratio_7d, has_spot_sync, oi_value, oi_change_pct, signal_strength, initial_confidence, status, is_active, max_price_increase, time_to_pump_hours, pump_realized, detection_method, created_at, updated_at) FROM stdin;
31	2124	ADAUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	109186849.55	67984029.98	58632874.67	\N	1.61	1.86	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	3.29	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
32	2125	XMRUSDT	2025-11-01 04:00:00+00	2025-11-01 04:00:00+00	9914239.10	3760993.13	4458582.82	\N	2.64	2.22	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	11.07	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
33	2125	XMRUSDT	2025-11-02 08:00:00+00	2025-11-02 08:00:00+00	10475889.51	4104954.50	4528069.17	\N	2.55	2.31	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.65	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
34	2125	XMRUSDT	2025-11-03 16:00:00+00	2025-11-03 16:00:00+00	7572073.91	4397273.18	4692919.17	\N	1.72	1.61	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	9.51	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
35	2125	XMRUSDT	2025-11-04 04:00:00+00	2025-11-04 04:00:00+00	9800896.68	4628301.89	4767947.94	\N	2.12	2.06	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	10.70	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
36	2125	XMRUSDT	2025-11-05 08:00:00+00	2025-11-05 08:00:00+00	23488479.81	5277242.32	4971862.07	\N	4.45	4.72	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	4.84	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
37	2126	DASHUSDT	2025-10-31 20:00:00+00	2025-10-31 20:00:00+00	19067176.79	10746767.56	10562054.36	\N	1.77	1.81	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	183.77	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
38	2126	DASHUSDT	2025-11-01 12:00:00+00	2025-11-01 12:00:00+00	270973196.34	17080852.30	13236064.70	\N	15.86	20.47	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	111.57	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
39	2126	DASHUSDT	2025-11-02 04:00:00+00	2025-11-02 04:00:00+00	237769463.75	28945701.83	19059026.97	\N	8.21	12.48	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	67.64	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
40	2126	DASHUSDT	2025-11-03 16:00:00+00	2025-11-03 16:00:00+00	308176065.66	54315651.35	32960268.12	\N	5.67	9.35	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	32.12	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
41	2126	DASHUSDT	2025-11-04 04:00:00+00	2025-11-04 04:00:00+00	372150296.69	69338377.90	40305581.82	\N	5.37	9.23	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	16.20	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
42	2127	ZECUSDT	2025-10-31 04:00:00+00	2025-10-31 04:00:00+00	371773475.76	180945302.71	144725403.71	\N	2.05	2.57	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	42.63	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
43	2127	ZECUSDT	2025-11-01 12:00:00+00	2025-11-01 12:00:00+00	568311435.70	229935455.09	167899809.04	\N	2.47	3.38	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	31.44	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
44	2127	ZECUSDT	2025-11-02 12:00:00+00	2025-11-02 12:00:00+00	422617646.07	250391643.37	182878104.81	\N	1.69	2.31	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	45.95	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
45	2127	ZECUSDT	2025-11-04 12:00:00+00	2025-11-04 12:00:00+00	700551336.07	276374321.20	215729380.08	\N	2.53	3.25	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	39.09	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
46	2128	XTZUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	5413037.14	1529051.80	1467676.71	\N	3.54	3.69	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	25.14	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
47	2128	XTZUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	5547560.47	1765761.51	1597086.27	\N	3.14	3.47	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	27.08	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
48	2128	XTZUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	2861294.60	1839268.33	1639600.71	\N	1.56	1.75	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	25.62	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
49	2129	BNBUSDT	2025-10-31 08:00:00+00	2025-10-31 08:00:00+00	624176493.37	203208041.62	252782840.82	\N	3.07	2.47	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	1.46	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
50	2129	BNBUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	576233158.38	195969603.22	216586765.37	\N	2.94	2.66	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	4.58	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
51	2129	BNBUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	655310739.81	224272069.75	225185463.91	\N	2.92	2.91	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	3.22	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
52	2129	BNBUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	365584004.92	228879033.46	229807250.09	\N	1.60	1.59	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	1.89	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
53	2130	ATOMUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	26752321.37	7219536.23	6628805.02	\N	3.71	4.04	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.78	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
54	2130	ATOMUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	28766803.32	9103883.28	7431769.55	\N	3.16	3.87	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	7.15	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
55	2130	ATOMUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	14726893.13	9480178.03	7654727.44	\N	1.55	1.92	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	5.26	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
56	2131	ONTUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	2051073.12	715936.60	609971.99	\N	2.86	3.36	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.89	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
57	2131	ONTUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	2090308.65	776879.67	665245.51	\N	2.69	3.14	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.69	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
58	2131	ONTUSDT	2025-11-05 20:00:00+00	2025-11-05 20:00:00+00	1211239.63	784831.19	683287.24	\N	1.54	1.77	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	0.85	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
59	2132	IOTAUSDT	2025-10-31 12:00:00+00	2025-10-31 12:00:00+00	1943805.55	1248590.72	1275207.46	\N	1.56	1.52	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	3.45	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
60	2132	IOTAUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	3849955.13	1334066.57	1232272.94	\N	2.89	3.12	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.65	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
61	2132	IOTAUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	5577306.04	1481989.07	1344621.43	\N	3.76	4.15	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	4.03	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
62	2132	IOTAUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	3216384.45	1565443.51	1389260.96	\N	2.05	2.32	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	2.25	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
63	2134	VETUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	3884720.81	2338179.43	2346677.89	\N	1.66	1.66	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	4.59	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
64	2134	VETUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	9168891.26	2673930.03	2434232.32	\N	3.43	3.77	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.23	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
65	2134	VETUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	10186380.21	3259933.05	2691865.41	\N	3.12	3.78	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	10.07	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
66	2134	VETUSDT	2025-11-05 12:00:00+00	2025-11-05 12:00:00+00	7661478.19	3625257.96	2833823.30	\N	2.11	2.70	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	1.75	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
67	2135	NEOUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	6004657.57	1950744.41	1808616.82	\N	3.08	3.32	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	9.07	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
68	2135	NEOUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	7141894.02	2400992.61	2015250.99	\N	2.97	3.54	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.45	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
69	2135	NEOUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	6122434.49	2500604.83	2069575.87	\N	2.45	2.96	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	4.40	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
70	2137	IOSTUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1451676.18	322282.59	320195.89	\N	4.50	4.53	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	7.41	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
71	2137	IOSTUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1571205.91	419344.66	350084.14	\N	3.75	4.49	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.25	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
72	2137	IOSTUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	776733.20	442102.77	360760.84	\N	1.76	2.15	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.14	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
73	2138	THETAUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	9438929.50	1879730.92	1940019.45	\N	5.02	4.87	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	10.97	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
74	2138	THETAUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	8853966.75	2317231.80	2103700.40	\N	3.82	4.21	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.51	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
75	2138	THETAUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	4304968.65	2449766.16	2163510.06	\N	1.76	1.99	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	4.79	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
76	2139	ALGOUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	20095328.85	5382058.26	4684405.59	\N	3.73	4.29	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.88	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
77	2139	ALGOUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	15366523.83	5784230.28	5010661.90	\N	2.66	3.07	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.85	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
78	2140	ZILUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	1216554.16	748789.81	776643.24	\N	1.62	1.57	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	4.53	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
79	2140	ZILUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	2600344.06	814006.81	783576.07	\N	3.19	3.32	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.78	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
80	2140	ZILUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	3875281.84	983519.51	857688.39	\N	3.94	4.52	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.24	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
81	2140	ZILUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	2095240.08	1048398.08	888401.73	\N	2.00	2.36	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	4.61	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
82	2141	KNCUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1490828.28	387502.23	751081.69	\N	3.85	1.98	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	10.07	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
83	2141	KNCUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1243217.03	458794.90	576490.20	\N	2.71	2.16	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	8.25	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
84	2141	KNCUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	743934.07	472272.67	578472.34	\N	1.58	1.29	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	8.06	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
85	2141	KNCUSDT	2025-11-06 00:00:00+00	2025-11-06 00:00:00+00	1085853.65	454335.16	505559.32	\N	2.39	2.15	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	2.82	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
86	2142	ZRXUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	2222755.57	1036259.27	999519.17	\N	2.14	2.22	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	23.01	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
87	2142	ZRXUSDT	2025-11-04 16:00:00+00	2025-11-04 16:00:00+00	7287746.97	1102027.44	1033469.18	\N	6.61	7.05	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	15.13	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
88	2142	ZRXUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	2435757.79	1344929.12	1150208.53	\N	1.81	2.12	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	13.57	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
89	2143	COMPUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	3207028.25	2038541.82	2148710.11	\N	1.57	1.49	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	2.61	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
90	2143	COMPUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	5770926.81	2269566.53	1973018.98	\N	2.54	2.92	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.69	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
91	2143	COMPUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	5551161.61	2582234.29	2020431.56	\N	2.15	2.75	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	4.11	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
92	2144	DOGEUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	599821043.78	176395496.65	184493781.70	\N	3.40	3.25	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.27	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
93	2144	DOGEUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	644453502.12	206876980.19	194248358.67	\N	3.12	3.32	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	4.08	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
94	2144	DOGEUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	352684803.94	213207708.59	198391865.58	\N	1.65	1.78	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	2.70	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
95	2145	SXPUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1603838.17	455480.79	439867.18	\N	3.52	3.65	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	7.31	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
96	2145	SXPUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1748835.50	540812.03	468720.09	\N	3.23	3.73	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.97	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
97	2145	SXPUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	946996.57	568165.54	478392.61	\N	1.67	1.98	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	5.34	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
98	2146	KAVAUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	3059334.53	1804661.50	1882351.15	\N	1.70	1.63	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	15.48	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
99	2146	KAVAUSDT	2025-11-02 16:00:00+00	2025-11-02 16:00:00+00	13811245.28	1906348.35	1893970.21	\N	7.24	7.29	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	8.58	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
100	2146	KAVAUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	4581430.16	2348183.76	2047319.19	\N	1.95	2.24	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.70	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
101	2147	BANDUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1183945.64	509686.52	459138.77	\N	2.32	2.58	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.63	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
102	2147	BANDUSDT	2025-11-04 04:00:00+00	2025-11-04 04:00:00+00	1163165.64	527916.67	472240.69	\N	2.20	2.46	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	5.52	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
103	2147	BANDUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	1007759.92	545535.61	490907.24	\N	1.85	2.05	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	3.91	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
104	2148	RLCUSDT	2025-11-01 08:00:00+00	2025-11-01 08:00:00+00	4354813.37	653978.40	594120.48	\N	6.66	7.33	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	5.48	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
105	2148	RLCUSDT	2025-11-02 08:00:00+00	2025-11-02 08:00:00+00	1433860.69	889240.26	701901.90	\N	1.61	2.04	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	1.84	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
106	2148	RLCUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1686641.25	925627.90	755580.86	\N	1.82	2.23	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	2.18	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
107	2150	SNXUSDT	2025-11-02 08:00:00+00	2025-11-02 08:00:00+00	22047659.51	8686762.64	14679693.27	\N	2.54	1.50	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.60	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
108	2150	SNXUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	17288357.48	8917511.68	12135054.50	\N	1.94	1.42	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	8.77	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
109	2150	SNXUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	20272758.58	8824559.84	10614421.40	\N	2.30	1.91	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	3.43	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
110	2151	DOTUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	99096809.66	22844917.65	20847098.26	\N	4.34	4.75	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.22	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
111	2151	DOTUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	84727868.02	28260579.86	22735287.85	\N	3.00	3.73	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.98	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
112	2153	YFIUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	1780574.92	859576.42	829562.64	\N	2.07	2.15	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	4.99	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
113	2153	YFIUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	3453826.21	914100.12	827818.58	\N	3.78	4.17	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.40	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
114	2153	YFIUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	3412622.83	1104906.44	940904.80	\N	3.09	3.63	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	12.33	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
115	2153	YFIUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	2606604.17	1158916.70	966646.75	\N	2.25	2.70	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	10.97	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
116	2154	CRVUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	23718727.52	13348292.42	14123267.93	\N	1.78	1.68	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	0.61	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
117	2154	CRVUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	37827604.08	14090336.26	13803461.43	\N	2.68	2.74	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.41	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
118	2154	CRVUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	39236897.68	16081020.31	14539650.46	\N	2.44	2.70	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	4.74	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
119	2154	CRVUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	25541936.18	16465891.14	14780265.87	\N	1.55	1.73	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	4.74	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
120	2155	TRBUSDT	2025-11-01 20:00:00+00	2025-11-01 20:00:00+00	16715556.48	4159999.99	3639957.89	\N	4.02	4.59	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	4.60	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
121	2155	TRBUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	13626603.56	4829468.41	3973768.66	\N	2.82	3.43	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	10.54	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
122	2155	TRBUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	10223209.98	4929676.52	4198422.29	\N	2.07	2.44	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	2.94	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
123	2156	RUNEUSDT	2025-11-01 20:00:00+00	2025-11-01 20:00:00+00	8488575.11	1957776.22	1806261.89	\N	4.34	4.70	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	2.81	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
124	2156	RUNEUSDT	2025-11-02 16:00:00+00	2025-11-02 16:00:00+00	7599559.54	2169554.72	1874941.13	\N	3.50	4.05	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	1.88	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
125	2156	RUNEUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	4974141.62	2071241.45	1960883.36	\N	2.40	2.54	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	5.38	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
126	2156	RUNEUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	5285157.49	2269315.03	2047358.71	\N	2.33	2.58	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	1.31	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
127	2157	SUSHIUSDT	2025-11-01 08:00:00+00	2025-11-01 08:00:00+00	3852057.57	2325182.00	2317086.90	\N	1.66	1.66	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	1.74	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
128	2157	SUSHIUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	8745131.33	2358716.64	2299896.34	\N	3.71	3.80	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.92	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
129	2157	SUSHIUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	6923022.96	2746940.83	2443467.81	\N	2.52	2.83	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	5.58	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
130	2158	EGLDUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	2078199.18	1317592.68	1230688.40	\N	1.58	1.69	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	8.90	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
131	2158	EGLDUSDT	2025-11-01 08:00:00+00	2025-11-01 08:00:00+00	2361160.44	1362173.54	1222193.34	\N	1.73	1.93	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	4.99	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
132	2158	EGLDUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	4126841.63	1567959.00	1277837.78	\N	2.63	3.23	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.90	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
133	2158	EGLDUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	4636477.78	1771058.50	1408221.30	\N	2.62	3.29	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	4.01	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
134	2159	SOLUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	2011560179.25	753072056.78	705913481.36	\N	2.67	2.85	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.06	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
135	2159	SOLUSDT	2025-11-04 16:00:00+00	2025-11-04 16:00:00+00	1999728808.52	834381606.82	743539534.77	\N	2.40	2.69	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.04	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
136	2159	SOLUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	1370106127.03	876258192.04	765659360.33	\N	1.56	1.79	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	4.49	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
137	2161	STORJUSDT	2025-11-02 04:00:00+00	2025-11-02 04:00:00+00	2162851.63	524205.00	1235905.71	\N	4.13	1.75	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	2.66	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
138	2161	STORJUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	972292.19	613805.41	1289082.02	\N	1.58	0.75	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	16.88	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
139	2161	STORJUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1200063.77	648581.10	789447.22	\N	1.85	1.52	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	22.33	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
140	2162	UNIUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	49801294.40	17829564.68	16783580.61	\N	2.79	2.97	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.00	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
141	2162	UNIUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	64115017.66	20888794.84	17630038.49	\N	3.07	3.64	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.28	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
142	2163	AVAXUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	179546326.11	52851031.50	51946020.43	\N	3.40	3.46	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.09	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
143	2163	AVAXUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	199486020.25	61411079.19	55662248.29	\N	3.25	3.58	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.31	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
144	2163	AVAXUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	101714764.73	63954043.54	57048883.76	\N	1.59	1.78	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	3.38	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
145	2167	NEARUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	67327119.14	22536185.90	21563445.03	\N	2.99	3.12	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	10.69	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
146	2167	NEARUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	68796119.02	25610289.83	22736214.43	\N	2.69	3.03	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	14.86	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
147	2167	NEARUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	49704246.97	26410848.03	23217918.24	\N	1.88	2.14	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	12.95	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
148	2168	AAVEUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	80042424.52	21461702.86	25213980.43	\N	3.73	3.17	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	1.52	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
149	2168	AAVEUSDT	2025-11-02 16:00:00+00	2025-11-02 16:00:00+00	88514695.86	23972463.23	24586364.12	\N	3.69	3.60	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.43	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
150	2168	AAVEUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	76947306.05	26777376.60	25809905.37	\N	2.87	2.98	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.52	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
151	2168	AAVEUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	96276995.60	31702213.19	27616940.70	\N	3.04	3.49	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	9.50	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
152	2168	AAVEUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	83257750.91	33201185.65	28336950.35	\N	2.51	2.94	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	3.67	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
153	2169	FILUSDT	2025-11-01 12:00:00+00	2025-11-01 12:00:00+00	69232788.12	20508988.90	19314422.38	\N	3.38	3.58	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	15.63	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
154	2169	FILUSDT	2025-11-02 08:00:00+00	2025-11-02 08:00:00+00	78220946.04	23492825.59	20667427.85	\N	3.33	3.78	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	15.63	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
155	2169	FILUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	72913910.26	27370058.92	22538368.03	\N	2.66	3.24	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	31.75	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
156	2169	FILUSDT	2025-11-04 16:00:00+00	2025-11-04 16:00:00+00	86136309.03	32490236.71	24969973.52	\N	2.65	3.45	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	44.09	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
157	2170	RSRUSDT	2025-10-31 20:00:00+00	2025-10-31 20:00:00+00	5656848.95	1678951.81	1732040.32	\N	3.37	3.27	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	2.97	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
158	2170	RSRUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	3896145.51	1907853.42	1718118.88	\N	2.04	2.27	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.41	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
159	2170	RSRUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	4720288.99	2101721.98	1772049.13	\N	2.25	2.66	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	1.31	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
160	2172	BELUSDT	2025-10-31 04:00:00+00	2025-10-31 04:00:00+00	5771088.24	3255749.10	4848166.66	\N	1.77	1.19	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	4.73	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
161	2172	BELUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	3376611.42	1805889.04	3322239.84	\N	1.87	1.02	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	24.51	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
162	2172	BELUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	7242972.41	1892389.47	3269836.15	\N	3.83	2.22	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	18.91	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
163	2173	AXSUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	7015148.88	1945521.85	1779054.31	\N	3.61	3.94	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	9.21	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
164	2173	AXSUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	7276836.67	2386147.21	1935859.11	\N	3.05	3.76	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	4.64	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
165	2175	ZENUSDT	2025-10-31 20:00:00+00	2025-10-31 20:00:00+00	31049449.87	16107792.30	15166331.57	\N	1.93	2.05	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	71.82	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
166	2175	ZENUSDT	2025-11-01 04:00:00+00	2025-11-01 04:00:00+00	284452986.92	19513644.61	16766953.82	\N	14.58	16.97	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	23.29	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
167	2175	ZENUSDT	2025-11-02 04:00:00+00	2025-11-02 04:00:00+00	214624493.01	52879493.64	33183275.25	\N	4.06	6.47	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	25.17	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
168	2175	ZENUSDT	2025-11-03 16:00:00+00	2025-11-03 16:00:00+00	136059756.36	65434333.91	41412002.33	\N	2.08	3.29	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	37.91	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
169	2175	ZENUSDT	2025-11-04 04:00:00+00	2025-11-04 04:00:00+00	322484946.26	73687111.70	45454698.29	\N	4.38	7.09	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	18.62	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
170	2176	SKLUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1925143.61	1099342.09	1434303.97	\N	1.75	1.34	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	4.00	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
171	2177	GRTUSDT	2025-11-01 08:00:00+00	2025-11-01 08:00:00+00	2882853.85	1791241.78	1802525.16	\N	1.61	1.60	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	2.41	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
172	2177	GRTUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	6212026.94	2008390.16	1858802.44	\N	3.09	3.34	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.35	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
173	2177	GRTUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	6280678.53	2301816.51	1965042.74	\N	2.73	3.20	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	4.70	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
174	2178	1INCHUSDT	2025-11-01 16:00:00+00	2025-11-01 16:00:00+00	1415459.82	795326.57	789597.46	\N	1.78	1.79	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	34.02	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
175	2178	1INCHUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	3543526.87	905229.75	811451.01	\N	3.91	4.37	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	51.93	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
176	2178	1INCHUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	4234863.15	1150303.54	906814.17	\N	3.68	4.67	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	57.04	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
177	2178	1INCHUSDT	2025-11-05 20:00:00+00	2025-11-05 20:00:00+00	20278203.50	1552418.27	1113033.06	\N	13.06	18.22	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	20.07	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
178	2178	1INCHUSDT	2025-11-06 00:00:00+00	2025-11-06 00:00:00+00	68060032.84	2008182.66	1338812.19	\N	33.89	50.84	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	25.96	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
179	2179	CHZUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	6790188.37	1314713.17	1179445.36	\N	5.16	5.76	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	7.07	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
180	2179	CHZUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	6883789.65	1568147.23	1316395.46	\N	4.39	5.23	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	7.04	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
181	2179	CHZUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	2634943.19	1678246.53	1376386.71	\N	1.57	1.91	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	6.20	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
182	2180	SANDUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	10225588.16	3431765.32	3423292.08	\N	2.98	2.99	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.72	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
183	2180	SANDUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	13628766.05	4228432.25	3730948.82	\N	3.22	3.65	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.65	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
184	2180	SANDUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	6705500.80	4422067.36	3819991.73	\N	1.52	1.76	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	3.82	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
185	2182	RVNUSDT	2025-10-31 12:00:00+00	2025-10-31 12:00:00+00	981688.52	523784.36	551392.43	\N	1.87	1.78	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	24.87	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
186	2182	RVNUSDT	2025-11-01 08:00:00+00	2025-11-01 08:00:00+00	979542.36	557229.94	548579.27	\N	1.76	1.79	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	19.17	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
187	2182	RVNUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	2052402.94	635103.44	562949.62	\N	3.23	3.65	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	35.06	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
188	2182	RVNUSDT	2025-11-04 04:00:00+00	2025-11-04 04:00:00+00	4454168.35	705450.50	591841.60	\N	6.31	7.53	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	33.07	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
189	2182	RVNUSDT	2025-11-05 16:00:00+00	2025-11-05 16:00:00+00	22126978.73	983482.75	708003.17	\N	22.50	31.25	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	19.17	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
190	2182	RVNUSDT	2025-11-06 00:00:00+00	2025-11-06 00:00:00+00	3111004.27	1553360.40	996925.30	\N	2.00	3.12	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	4.63	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
191	2183	SFPUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	708004.80	358979.94	352592.68	\N	1.97	2.01	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.18	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
192	2183	SFPUSDT	2025-11-04 12:00:00+00	2025-11-04 12:00:00+00	1006123.23	400615.13	356608.40	\N	2.51	2.82	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	5.33	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
193	2184	COTIUSDT	2025-11-01 16:00:00+00	2025-11-01 16:00:00+00	1604461.11	585164.62	574301.37	\N	2.74	2.79	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	1.36	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
194	2184	COTIUSDT	2025-11-02 12:00:00+00	2025-11-02 12:00:00+00	1388258.45	642852.72	577636.15	\N	2.16	2.40	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	4.48	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
195	2184	COTIUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1641911.54	676807.65	595106.19	\N	2.43	2.76	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.87	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
196	2184	COTIUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1906424.43	725041.37	622873.73	\N	2.63	3.06	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	9.51	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
197	2185	CHRUSDT	2025-11-01 04:00:00+00	2025-11-01 04:00:00+00	3347610.53	965008.68	1079156.14	\N	3.47	3.10	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.73	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
198	2185	CHRUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	2012232.94	1156118.82	890378.95	\N	1.74	2.26	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	8.48	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
199	2186	MANAUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	3807849.11	2421626.85	2498822.44	\N	1.57	1.52	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	2.92	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
200	2186	MANAUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	9265679.93	2637687.60	2427652.20	\N	3.51	3.82	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	7.10	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
201	2186	MANAUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	12498638.70	3289861.12	2683465.07	\N	3.80	4.66	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	7.19	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
202	2187	ALICEUSDT	2025-11-01 12:00:00+00	2025-11-01 12:00:00+00	3732127.16	2155638.34	2534833.97	\N	1.73	1.47	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	1.06	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
203	2187	ALICEUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	3958817.81	1784603.08	2288928.94	\N	2.22	1.73	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	15.48	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
204	2187	ALICEUSDT	2025-11-04 16:00:00+00	2025-11-04 16:00:00+00	6550783.17	1778879.02	2242574.99	\N	3.68	2.92	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.15	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
205	2188	HBARUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	59768591.04	36998480.43	23928439.97	\N	1.62	2.50	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	5.39	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
206	2188	HBARUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	61968488.97	30685287.95	26171785.41	\N	2.02	2.37	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	4.90	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
207	2190	DENTUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	631105.24	411618.95	426378.99	\N	1.53	1.48	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	7.99	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
208	2190	DENTUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1402211.16	468299.92	422760.25	\N	2.99	3.32	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	9.46	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
209	2190	DENTUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1135549.62	512133.38	445248.54	\N	2.22	2.55	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	4.03	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
210	2190	DENTUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	938997.29	521433.94	449326.18	\N	1.80	2.09	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	2.93	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
211	2191	CELRUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	688502.29	388675.11	343486.66	\N	1.77	2.00	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	8.83	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
212	2191	CELRUSDT	2025-11-01 16:00:00+00	2025-11-01 16:00:00+00	677192.41	412736.63	354101.25	\N	1.64	1.91	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	3.02	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
213	2191	CELRUSDT	2025-11-02 12:00:00+00	2025-11-02 12:00:00+00	1061231.04	432628.59	367832.05	\N	2.45	2.89	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	5.27	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
214	2191	CELRUSDT	2025-11-03 04:00:00+00	2025-11-03 04:00:00+00	883281.99	468091.73	384881.38	\N	1.89	2.29	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	2.86	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
215	2191	CELRUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	972295.83	521071.38	412259.93	\N	1.87	2.36	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	10.58	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
216	2191	CELRUSDT	2025-11-06 00:00:00+00	2025-11-06 00:00:00+00	947721.17	539473.60	428700.23	\N	1.76	2.21	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	1.35	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
217	2192	HOTUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	846001.58	502067.69	1047253.98	\N	1.69	0.81	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	5.29	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
218	2192	HOTUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	2409158.94	569604.32	566993.49	\N	4.23	4.25	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	11.88	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
219	2192	HOTUSDT	2025-11-04 16:00:00+00	2025-11-04 16:00:00+00	1688607.27	654169.92	591887.97	\N	2.58	2.85	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	17.94	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
220	2192	HOTUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	1139626.64	688049.76	601517.75	\N	1.66	1.89	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	13.90	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
221	2193	MTLUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	684370.72	245140.25	227515.71	\N	2.79	3.01	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.47	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
222	2193	MTLUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	625580.36	268709.26	244941.07	\N	2.33	2.55	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	8.43	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
223	2193	MTLUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	456224.97	276510.14	249284.24	\N	1.65	1.83	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	8.24	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
224	2194	OGNUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	988678.36	333917.16	313040.47	\N	2.96	3.16	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.46	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
225	2194	OGNUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1756319.32	376694.55	327928.10	\N	4.66	5.36	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	4.66	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
226	2194	OGNUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	1191173.36	403888.04	336194.84	\N	2.95	3.54	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.04	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
227	2195	NKNUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	756186.58	229106.27	219359.89	\N	3.30	3.45	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.11	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
228	2195	NKNUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	685932.37	246355.85	232147.60	\N	2.78	2.95	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	3.78	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
229	2195	NKNUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	509255.68	253541.02	236451.95	\N	2.01	2.15	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	5.19	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
230	2196	1000SHIBUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	53948812.41	14798202.29	14206060.35	\N	3.65	3.80	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	4.84	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
231	2196	1000SHIBUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	56227357.33	18227977.44	15322510.77	\N	3.08	3.67	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	4.34	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
232	2196	1000SHIBUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	33609871.39	18841459.16	15706228.18	\N	1.78	2.14	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	1.76	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
233	2198	GTCUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1056836.20	498664.30	446326.30	\N	2.12	2.37	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	9.94	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
234	2198	GTCUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1099581.32	520504.88	455205.04	\N	2.11	2.42	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.27	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
235	2199	BTCDOMUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	6361736.74	1494225.89	1470646.61	\N	4.26	4.33	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.57	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
236	2199	BTCDOMUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	14341859.09	2112845.97	1726734.96	\N	6.79	8.31	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	3.86	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
237	2199	BTCDOMUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	6695708.85	2386279.97	1873976.57	\N	2.81	3.57	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	2.98	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
238	2200	IOTXUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	787397.21	412098.56	516870.32	\N	1.91	1.52	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	10.59	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
239	2200	IOTXUSDT	2025-11-02 12:00:00+00	2025-11-02 12:00:00+00	1486776.70	449395.66	513509.21	\N	3.31	2.90	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.14	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
240	2200	IOTXUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1885574.26	509071.88	530964.13	\N	3.70	3.55	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.03	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
241	2200	IOTXUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1329473.42	611261.52	526921.60	\N	2.17	2.52	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	5.01	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
242	2201	C98USDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	2635479.60	718827.26	705810.63	\N	3.67	3.73	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	9.93	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
243	2201	C98USDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1752758.20	824644.87	741609.37	\N	2.13	2.36	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	3.77	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
244	2201	C98USDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	1572441.53	836871.01	747795.06	\N	1.88	2.10	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	3.45	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
245	2203	ATAUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1146185.01	487653.40	392984.44	\N	2.35	2.92	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	10.09	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
246	2203	ATAUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	927371.43	518874.35	423785.58	\N	1.79	2.19	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	9.13	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
247	2204	DYDXUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	11922887.84	6431048.97	5861323.31	\N	1.85	2.03	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.97	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
248	2204	DYDXUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	14001036.28	7089620.81	5797766.02	\N	1.97	2.41	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	11.65	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
249	2204	DYDXUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	14394077.76	7579442.20	6089263.42	\N	1.90	2.36	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	8.18	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
250	2206	GALAUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	10650130.20	6656233.73	6858430.30	\N	1.60	1.55	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	4.23	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
251	2206	GALAUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	28328465.57	7451133.36	6829072.20	\N	3.80	4.15	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	9.68	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
252	2206	GALAUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	26278465.01	8798420.18	7378348.89	\N	2.99	3.56	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	7.29	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
253	2207	CELOUSDT	2025-11-02 12:00:00+00	2025-11-02 12:00:00+00	11984651.89	3305589.71	4000653.09	\N	3.63	3.00	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	9.20	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
254	2207	CELOUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	6346972.47	3557076.93	4100494.57	\N	1.78	1.55	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	7.33	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
255	2207	CELOUSDT	2025-11-04 16:00:00+00	2025-11-04 16:00:00+00	7952975.53	3908028.12	4093105.30	\N	2.04	1.94	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	9.86	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
256	2208	ARUSDT	2025-11-01 12:00:00+00	2025-11-01 12:00:00+00	15793422.59	3663247.56	3020468.94	\N	4.31	5.23	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	37.61	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
257	2208	ARUSDT	2025-11-02 04:00:00+00	2025-11-02 04:00:00+00	18941086.46	4612486.02	3504454.23	\N	4.11	5.40	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	32.28	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
258	2208	ARUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	9370119.71	5760005.31	4117304.39	\N	1.63	2.28	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	56.82	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
259	2208	ARUSDT	2025-11-04 04:00:00+00	2025-11-04 04:00:00+00	20949422.01	5685299.91	4322995.71	\N	3.68	4.85	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	45.10	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
260	2208	ARUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	15194529.92	7101256.80	5106710.02	\N	2.14	2.98	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	28.19	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
261	2209	ARPAUSDT	2025-11-01 04:00:00+00	2025-11-01 04:00:00+00	1497177.59	442541.81	791336.95	\N	3.38	1.89	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.10	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
262	2209	ARPAUSDT	2025-11-02 08:00:00+00	2025-11-02 08:00:00+00	3028591.99	495161.18	693040.44	\N	6.12	4.37	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	3.78	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
263	2209	ARPAUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1162962.40	585468.97	675828.98	\N	1.99	1.72	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	11.45	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
264	2209	ARPAUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1615510.23	625533.52	656112.36	\N	2.58	2.46	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	11.81	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
265	2209	ARPAUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	1120466.24	646573.87	662811.30	\N	1.73	1.69	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	12.02	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
266	2210	CTSIUSDT	2025-11-02 08:00:00+00	2025-11-02 08:00:00+00	1278245.24	346541.02	650534.18	\N	3.69	1.96	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	1.95	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
267	2210	CTSIUSDT	2025-11-03 00:00:00+00	2025-11-03 00:00:00+00	788713.07	400027.66	677839.46	\N	1.97	1.16	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	10.33	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
268	2210	CTSIUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1109444.48	447889.75	398320.45	\N	2.48	2.79	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	5.40	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
269	2211	LPTUSDT	2025-11-01 08:00:00+00	2025-11-01 08:00:00+00	38723885.89	1709884.26	1621917.54	\N	22.65	23.88	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	19.23	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
270	2211	LPTUSDT	2025-11-02 00:00:00+00	2025-11-02 00:00:00+00	105798898.86	4322259.31	2923386.98	\N	24.48	36.19	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	4.03	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
271	2211	LPTUSDT	2025-11-03 00:00:00+00	2025-11-03 00:00:00+00	22884469.70	10160529.75	5848089.25	\N	2.25	3.91	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	11.59	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
272	2211	LPTUSDT	2025-11-04 04:00:00+00	2025-11-04 04:00:00+00	18687614.32	12068771.33	6836649.39	\N	1.55	2.73	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.98	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
273	2212	ENSUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	11635898.90	3002511.22	3087350.50	\N	3.88	3.77	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	7.74	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
274	2212	ENSUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	14330771.90	3785209.85	3375577.90	\N	3.79	4.25	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	4.47	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
275	2212	ENSUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	9978192.26	3977957.85	3486163.46	\N	2.51	2.86	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	2.80	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
276	2213	PEOPLEUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	4460544.53	2128058.51	2209650.00	\N	2.10	2.02	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.32	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
277	2213	PEOPLEUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	9894695.98	2353413.96	2122060.45	\N	4.20	4.66	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	11.52	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
278	2213	PEOPLEUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	6911918.34	2816109.11	2315792.83	\N	2.45	2.98	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	4.37	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
279	2214	ROSEUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	1755375.84	1135788.95	1122005.54	\N	1.55	1.56	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	46.75	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
280	2214	ROSEUSDT	2025-11-01 16:00:00+00	2025-11-01 16:00:00+00	6544830.73	1308166.91	1193742.43	\N	5.00	5.48	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	30.71	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
281	2214	ROSEUSDT	2025-11-02 04:00:00+00	2025-11-02 04:00:00+00	11439199.25	1492982.50	1283049.92	\N	7.66	8.92	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	22.60	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
282	2214	ROSEUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	4823889.80	2437065.83	1746448.39	\N	1.98	2.76	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	48.62	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
283	2214	ROSEUSDT	2025-11-04 04:00:00+00	2025-11-04 04:00:00+00	11841381.50	2698363.22	1881274.45	\N	4.39	6.29	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	28.36	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
284	2214	ROSEUSDT	2025-11-05 12:00:00+00	2025-11-05 12:00:00+00	5342965.05	3554952.15	2272984.32	\N	1.50	2.35	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	25.67	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
285	2215	DUSKUSDT	2025-11-01 04:00:00+00	2025-11-01 04:00:00+00	1790466.36	346122.39	339446.16	\N	5.17	5.27	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	56.24	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
286	2215	DUSKUSDT	2025-11-02 04:00:00+00	2025-11-02 04:00:00+00	3017402.08	483793.76	391258.24	\N	6.24	7.71	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	43.79	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
287	2215	DUSKUSDT	2025-11-03 00:00:00+00	2025-11-03 00:00:00+00	1336637.12	616583.92	467976.47	\N	2.17	2.86	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	66.87	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
288	2215	DUSKUSDT	2025-11-04 04:00:00+00	2025-11-04 04:00:00+00	4987035.46	760946.32	550187.86	\N	6.55	9.06	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	34.16	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
289	2215	DUSKUSDT	2025-11-05 12:00:00+00	2025-11-05 12:00:00+00	4583185.33	1271968.86	797385.13	\N	3.60	5.75	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	34.88	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
290	2217	IMXUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	6328883.01	2405484.28	2462808.50	\N	2.63	2.57	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	8.85	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
291	2217	IMXUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	8311326.42	2640219.50	2568086.68	\N	3.15	3.24	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	1.29	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
292	2217	IMXUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	5800266.18	2751780.86	2625654.08	\N	2.11	2.21	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	0.61	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
293	2218	API3USDT	2025-10-31 04:00:00+00	2025-10-31 04:00:00+00	18513677.59	2006345.27	3776383.18	\N	9.23	4.90	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	4.21	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
294	2218	API3USDT	2025-11-01 00:00:00+00	2025-11-01 00:00:00+00	5336607.72	2929165.40	3988844.85	\N	1.82	1.34	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	4.45	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
295	2218	API3USDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	6419657.80	3102918.31	2861050.82	\N	2.07	2.24	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	8.40	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
296	2218	API3USDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	7613938.05	3496062.87	2839611.17	\N	2.18	2.68	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	4.77	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
297	2219	GMTUSDT	2025-11-01 08:00:00+00	2025-11-01 08:00:00+00	2413546.56	1064992.23	1179626.98	\N	2.27	2.05	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	2.68	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
298	2219	GMTUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	3413398.86	1165300.66	1217719.11	\N	2.93	2.80	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.14	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
299	2219	GMTUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	4606128.75	1318464.36	1280679.83	\N	3.49	3.60	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.26	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
300	2220	APEUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	7912142.05	3716730.51	4844258.58	\N	2.13	1.63	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.72	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
301	2220	APEUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	8797786.67	3426633.61	4762319.63	\N	2.57	1.85	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	8.53	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
302	2220	APEUSDT	2025-11-05 20:00:00+00	2025-11-05 20:00:00+00	7258511.55	3429295.24	4799739.46	\N	2.12	1.51	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	0.68	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
303	2221	WOOUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1557883.92	480755.19	457476.78	\N	3.24	3.41	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	9.68	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
304	2221	WOOUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1299776.82	557814.11	492234.76	\N	2.33	2.64	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.45	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
305	2222	JASMYUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	5249239.61	1504627.54	1804817.40	\N	3.49	2.91	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	7.04	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
306	2222	JASMYUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	6337989.95	1874568.72	1955142.08	\N	3.38	3.24	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	9.40	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
307	2222	JASMYUSDT	2025-11-05 12:00:00+00	2025-11-05 12:00:00+00	3769394.11	2044960.12	2015459.55	\N	1.84	1.87	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	2.69	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
308	2223	OPUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	43497971.71	13303601.17	12161366.24	\N	3.27	3.58	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	9.49	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
309	2223	OPUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	43502034.38	15654271.12	13158664.98	\N	2.78	3.31	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	9.27	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
310	2224	INJUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	15317019.00	8474096.50	8758898.63	\N	1.81	1.75	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	5.55	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
311	2224	INJUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	31315983.66	9883974.82	9062280.62	\N	3.17	3.46	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	9.30	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
312	2224	INJUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	41674843.79	11940941.28	9820396.89	\N	3.49	4.24	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.05	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
313	2224	INJUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	20279071.71	12597542.10	10166274.08	\N	1.61	1.99	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	2.77	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
314	2225	STGUSDT	2025-11-02 04:00:00+00	2025-11-02 04:00:00+00	798452.00	400730.04	403495.48	\N	1.99	1.98	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	0.48	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
315	2225	STGUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	2976690.52	464602.07	424526.43	\N	6.41	7.01	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	8.92	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
316	2225	STGUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	2366519.35	639623.85	503981.75	\N	3.70	4.70	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	10.40	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
317	2227	1000LUNCUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	3669653.12	1091760.11	1457060.03	\N	3.36	2.52	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.92	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
318	2227	1000LUNCUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	5499960.97	1265451.33	1376643.48	\N	4.35	4.00	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	3.04	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
319	2227	1000LUNCUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	2598283.88	1357199.90	1403449.39	\N	1.91	1.85	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	1.85	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
320	2228	LUNA2USDT	2025-11-02 12:00:00+00	2025-11-02 12:00:00+00	940966.03	599142.35	745770.90	\N	1.57	1.26	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	4.03	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
321	2228	LUNA2USDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1973815.10	633429.15	753832.31	\N	3.12	2.62	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	7.85	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
322	2228	LUNA2USDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1884203.95	692838.85	665231.04	\N	2.72	2.83	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	3.40	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
323	2229	LDOUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	15342245.95	10074232.77	10501718.70	\N	1.52	1.46	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	1.48	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
324	2229	LDOUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	33776862.97	10689856.10	10108494.37	\N	3.16	3.34	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.45	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
325	2229	LDOUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	48919583.49	12735328.51	10853015.86	\N	3.84	4.51	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.96	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
326	2229	LDOUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	20942542.27	13436063.59	11249292.98	\N	1.56	1.86	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	5.43	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
327	2230	ICPUSDT	2025-10-31 12:00:00+00	2025-10-31 12:00:00+00	6923220.16	4196086.36	4362442.34	\N	1.65	1.59	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	146.07	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
328	2230	ICPUSDT	2025-11-01 12:00:00+00	2025-11-01 12:00:00+00	54758751.10	5179935.66	4686216.55	\N	10.57	11.69	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	110.33	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
329	2230	ICPUSDT	2025-11-02 12:00:00+00	2025-11-02 12:00:00+00	84492944.22	8546081.78	6321340.55	\N	9.89	13.37	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	82.59	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
330	2230	ICPUSDT	2025-11-03 00:00:00+00	2025-11-03 00:00:00+00	63901605.77	12761149.60	8425619.72	\N	5.01	7.58	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	82.36	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
331	2230	ICPUSDT	2025-11-04 04:00:00+00	2025-11-04 04:00:00+00	142223111.09	21323036.61	12706814.85	\N	6.67	11.19	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	48.01	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
332	2230	ICPUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	85964895.52	40299852.55	22079438.59	\N	2.13	3.89	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	41.04	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
333	2230	ICPUSDT	2025-11-06 00:00:00+00	2025-11-06 00:00:00+00	73618021.67	48705433.16	26221922.51	\N	1.51	2.81	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	22.85	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
334	2231	APTUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	57549347.87	15970546.47	17338418.02	\N	3.60	3.32	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	10.16	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
335	2231	APTUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	51556296.79	20066639.10	19172124.13	\N	2.57	2.69	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	8.08	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
336	2232	QNTUSDT	2025-10-31 12:00:00+00	2025-10-31 12:00:00+00	1843330.72	1163832.51	1096209.24	\N	1.58	1.68	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	11.80	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
337	2232	QNTUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	2922503.32	1210381.18	1098970.53	\N	2.41	2.66	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	20.45	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
338	2232	QNTUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	2654498.74	1282272.44	1156925.09	\N	2.07	2.29	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	22.36	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
339	2232	QNTUSDT	2025-11-05 12:00:00+00	2025-11-05 12:00:00+00	10101002.90	1348659.43	1201957.07	\N	7.49	8.40	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	4.21	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
340	2232	QNTUSDT	2025-11-06 00:00:00+00	2025-11-06 00:00:00+00	3022394.94	1711313.15	1405676.78	\N	1.77	2.15	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	3.41	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
341	2233	FETUSDT	2025-11-02 12:00:00+00	2025-11-02 12:00:00+00	23903604.43	8641492.67	10947953.35	\N	2.77	2.18	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	9.00	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
342	2233	FETUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	31239744.59	9151984.96	10041814.30	\N	3.41	3.11	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	11.73	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
343	2233	FETUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	25584034.42	10572525.09	10155425.24	\N	2.42	2.52	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	10.41	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
344	2235	HOOKUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1538329.92	596238.31	613526.07	\N	2.58	2.51	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	10.21	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
345	2235	HOOKUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1525275.23	658656.82	624239.96	\N	2.32	2.44	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.26	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
346	2237	TUSDT	2025-11-02 16:00:00+00	2025-11-02 16:00:00+00	12604599.73	265337.81	337778.22	\N	47.50	37.32	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	4.57	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
347	2237	TUSDT	2025-11-03 00:00:00+00	2025-11-03 00:00:00+00	7101094.73	730075.17	569467.55	\N	9.73	12.47	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	11.70	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
348	2237	TUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	2154248.87	1093001.33	724379.82	\N	1.97	2.97	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	3.48	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
349	2238	HIGHUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	736316.91	259066.32	242122.16	\N	2.84	3.04	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	7.56	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
350	2238	HIGHUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	695165.83	295201.30	258538.39	\N	2.35	2.69	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	5.51	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
351	2239	MINAUSDT	2025-11-01 16:00:00+00	2025-11-01 16:00:00+00	97873136.39	1239100.48	1136323.64	\N	78.99	86.13	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	61.32	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
352	2239	MINAUSDT	2025-11-02 04:00:00+00	2025-11-02 04:00:00+00	111621844.94	5668034.42	3355441.39	\N	19.69	33.27	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	37.31	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
353	2239	MINAUSDT	2025-11-03 00:00:00+00	2025-11-03 00:00:00+00	64136434.30	18700043.95	9877910.56	\N	3.43	6.49	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	50.63	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
354	2239	MINAUSDT	2025-11-04 04:00:00+00	2025-11-04 04:00:00+00	82392282.89	23078815.19	12075025.88	\N	3.57	6.82	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	39.62	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
355	2240	ASTRUSDT	2025-11-02 12:00:00+00	2025-11-02 12:00:00+00	3129201.60	493527.38	408717.14	\N	6.34	7.66	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	4.49	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
356	2240	ASTRUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1416039.40	597887.05	457963.06	\N	2.37	3.09	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.86	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
357	2240	ASTRUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1535514.77	719597.74	501082.54	\N	2.13	3.06	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.29	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
358	2240	ASTRUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	1249096.61	744228.92	513335.14	\N	1.68	2.43	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.01	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
359	2242	GMXUSDT	2025-11-03 20:00:00+00	2025-11-03 20:00:00+00	1573221.29	894242.70	706506.62	\N	1.76	2.23	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	3.56	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
360	2242	GMXUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	2060540.79	953849.07	733238.41	\N	2.16	2.81	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	8.11	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
361	2242	GMXUSDT	2025-11-05 04:00:00+00	2025-11-05 04:00:00+00	1673072.81	1006486.86	761438.04	\N	1.66	2.20	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	2.65	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
362	2243	CFXUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	8240220.62	2434415.89	2293967.02	\N	3.38	3.59	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.20	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
363	2243	CFXUSDT	2025-11-04 16:00:00+00	2025-11-04 16:00:00+00	9246681.51	2530951.99	2391405.09	\N	3.65	3.87	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	7.32	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
364	2243	CFXUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	5010004.17	2825445.80	2521911.31	\N	1.77	1.99	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	1.97	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
365	2244	STXUSDT	2025-10-31 04:00:00+00	2025-10-31 04:00:00+00	5182059.73	1689630.52	2002323.78	\N	3.07	2.59	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.14	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
366	2244	STXUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	5186980.31	1924200.43	1755178.17	\N	2.70	2.96	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.73	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
367	2244	STXUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	6620977.77	2221347.94	1873694.45	\N	2.98	3.53	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	2.42	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
368	2244	STXUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	3872026.65	2324406.90	1924549.66	\N	1.67	2.01	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	0.94	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
369	2245	ACHUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	1362759.14	899030.86	954547.85	\N	1.52	1.43	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	1.65	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
370	2245	ACHUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	3502547.94	987170.11	961261.05	\N	3.55	3.64	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	7.23	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
371	2245	ACHUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	4765790.16	1205822.20	1049886.79	\N	3.95	4.54	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.81	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
372	2245	ACHUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	3200327.70	1276444.68	1086109.60	\N	2.51	2.95	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.54	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
373	2246	SSVUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	2269727.56	918210.16	942687.82	\N	2.47	2.41	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	10.22	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
374	2246	SSVUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	2434497.72	1037819.87	936875.83	\N	2.35	2.60	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.92	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
375	2246	SSVUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	2267842.42	1046331.84	947714.60	\N	2.17	2.39	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	4.79	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
376	2247	CKBUSDT	2025-11-02 04:00:00+00	2025-11-02 04:00:00+00	2231434.43	1185471.15	781795.99	\N	1.88	2.85	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	2.11	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
377	2247	CKBUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	2036434.72	1353143.78	914639.25	\N	1.50	2.23	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	8.31	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
378	2249	TRUUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	1356693.38	722629.33	1782096.32	\N	1.88	0.76	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	2.93	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
379	2249	TRUUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1824575.50	681662.34	745391.98	\N	2.68	2.45	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	5.98	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
380	2249	TRUUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1195795.77	679135.93	658368.95	\N	1.76	1.82	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	2.84	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
381	2250	LQTYUSDT	2025-11-06 00:00:00+00	2025-11-06 00:00:00+00	3860325.56	1698046.84	1620957.65	\N	2.27	2.38	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.36	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
382	2251	USDCUSDT	2025-10-31 12:00:00+00	2025-10-31 12:00:00+00	2045087.33	983670.66	1127538.47	\N	2.08	1.81	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	0.01	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
383	2251	USDCUSDT	2025-11-01 20:00:00+00	2025-11-01 20:00:00+00	1757278.75	1099960.99	1125295.98	\N	1.60	1.56	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	0.03	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
384	2251	USDCUSDT	2025-11-02 12:00:00+00	2025-11-02 12:00:00+00	2207879.46	1161135.50	1140768.46	\N	1.90	1.94	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	0.05	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
385	2251	USDCUSDT	2025-11-03 16:00:00+00	2025-11-03 16:00:00+00	3978188.17	1312812.67	1211369.59	\N	3.03	3.28	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	0.04	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
386	2251	USDCUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	7524678.59	1770409.08	1414801.40	\N	4.25	5.32	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	0.04	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
387	2251	USDCUSDT	2025-11-05 12:00:00+00	2025-11-05 12:00:00+00	3728592.63	1988067.69	1481371.40	\N	1.88	2.52	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	0.04	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
388	2253	ARBUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	28256833.53	16721841.48	16220988.96	\N	1.69	1.74	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	5.55	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
389	2253	ARBUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	63554846.98	17688431.17	16275089.68	\N	3.59	3.91	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.84	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
390	2253	ARBUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	78458832.81	21588121.13	18066654.10	\N	3.63	4.34	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.60	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
391	2253	ARBUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	37899179.66	22696957.64	18698095.69	\N	1.67	2.03	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	3.71	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
392	2254	JOEUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1076731.79	315426.00	294993.07	\N	3.41	3.65	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.36	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
393	2254	JOEUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	855502.36	350980.01	315964.42	\N	2.44	2.71	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.27	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
394	2255	TLMUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1160066.03	303565.26	363202.04	\N	3.82	3.19	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	22.22	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
395	2255	TLMUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	809387.82	341991.57	363757.78	\N	2.37	2.23	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	21.50	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
396	2255	TLMUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	535665.02	346450.24	367560.84	\N	1.55	1.46	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	19.99	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
397	2258	HFTUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1728085.90	632881.73	599574.18	\N	2.73	2.88	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	12.10	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
398	2258	HFTUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	2704295.76	736561.77	622388.11	\N	3.67	4.35	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.10	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
399	2258	HFTUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	2176879.27	778525.20	642526.75	\N	2.80	3.39	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.56	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
400	2260	BLURUSDT	2025-11-01 16:00:00+00	2025-11-01 16:00:00+00	4890027.57	695176.73	737321.52	\N	7.03	6.63	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	8.68	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
401	2260	BLURUSDT	2025-11-02 08:00:00+00	2025-11-02 08:00:00+00	4195401.56	868994.84	821372.20	\N	4.83	5.11	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	0.56	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
402	2260	BLURUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	2647096.25	1151268.63	922660.94	\N	2.30	2.87	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.16	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
403	2260	BLURUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	3196556.72	1347071.20	994286.91	\N	2.37	3.21	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.85	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
404	2261	EDUUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	2951934.87	1378366.48	2975085.98	\N	2.14	0.99	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	12.46	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
405	2261	EDUUSDT	2025-11-04 04:00:00+00	2025-11-04 04:00:00+00	3012982.31	1322736.76	2754488.31	\N	2.28	1.09	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	8.09	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
406	2262	SUIUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	218051428.18	81361296.87	79545799.24	\N	2.68	2.74	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.29	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
407	2262	SUIUSDT	2025-11-04 16:00:00+00	2025-11-04 16:00:00+00	250506450.62	87818634.18	82769931.98	\N	2.85	3.03	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	7.35	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
408	2263	1000PEPEUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	213362960.51	62286786.25	61582628.46	\N	3.43	3.46	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	7.41	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
409	2263	1000PEPEUSDT	2025-11-04 16:00:00+00	2025-11-04 16:00:00+00	257479040.19	73218632.80	65515206.44	\N	3.52	3.93	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.29	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
410	2264	1000FLOKIUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	22827245.25	6322140.63	10847160.11	\N	3.61	2.10	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.11	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
411	2264	1000FLOKIUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	29649254.73	7628377.76	7408463.36	\N	3.89	4.00	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.24	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
412	2266	NMRUSDT	2025-11-01 12:00:00+00	2025-11-01 12:00:00+00	4411183.57	1836549.01	2078487.48	\N	2.40	2.12	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	14.39	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
413	2266	NMRUSDT	2025-11-02 16:00:00+00	2025-11-02 16:00:00+00	34992063.67	1972019.70	2010625.93	\N	17.74	17.40	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	7.12	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
414	2266	NMRUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	27931597.88	3195998.69	2586151.43	\N	8.74	10.80	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	8.98	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
415	2266	NMRUSDT	2025-11-04 04:00:00+00	2025-11-04 04:00:00+00	10488240.47	4116301.94	2997455.52	\N	2.55	3.50	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.10	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
416	2266	NMRUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	7502539.21	4796833.05	3252667.47	\N	1.56	2.31	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	1.43	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
417	2267	MAVUSDT	2025-11-02 08:00:00+00	2025-11-02 08:00:00+00	2063544.59	398362.74	396569.85	\N	5.18	5.20	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	1.40	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
418	2267	MAVUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	870511.50	494421.36	442505.24	\N	1.76	1.97	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	9.47	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
419	2268	XVGUSDT	2025-11-01 08:00:00+00	2025-11-01 08:00:00+00	26084850.04	1951525.08	1532721.15	\N	13.37	17.02	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	30.48	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
420	2268	XVGUSDT	2025-11-02 04:00:00+00	2025-11-02 04:00:00+00	15855003.63	3222782.27	2207891.57	\N	4.92	7.18	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	22.02	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
421	2268	XVGUSDT	2025-11-03 16:00:00+00	2025-11-03 16:00:00+00	8821848.83	3807403.22	2758050.65	\N	2.32	3.20	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	29.04	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
422	2268	XVGUSDT	2025-11-04 04:00:00+00	2025-11-04 04:00:00+00	25303868.52	4304488.04	2992636.77	\N	5.88	8.46	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	17.86	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
423	2268	XVGUSDT	2025-11-05 16:00:00+00	2025-11-05 16:00:00+00	14428224.17	6082793.48	3818717.19	\N	2.37	3.78	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	2.25	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
424	2269	WLDUSDT	2025-11-01 08:00:00+00	2025-11-01 08:00:00+00	80428547.11	23050277.65	23578944.00	\N	3.49	3.41	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	3.56	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
425	2269	WLDUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	77907587.79	25243579.69	25565545.47	\N	3.09	3.05	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.38	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
426	2269	WLDUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	82179518.42	29566114.39	26498853.61	\N	2.78	3.10	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.83	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
427	2270	PENDLEUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	12882164.36	4777806.98	5240410.51	\N	2.70	2.46	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.22	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
428	2270	PENDLEUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	16996876.55	5299574.73	5279342.16	\N	3.21	3.22	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	4.68	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
429	2270	PENDLEUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	9374462.15	5551817.50	5394492.87	\N	1.69	1.74	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	3.83	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
430	2271	ARKMUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	4336904.84	2737413.93	2838353.24	\N	1.58	1.53	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	11.70	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
431	2271	ARKMUSDT	2025-11-01 20:00:00+00	2025-11-01 20:00:00+00	6169617.24	3010715.91	2865055.96	\N	2.05	2.15	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	1.21	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
432	2271	ARKMUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	11173942.75	3425599.79	2997563.71	\N	3.26	3.73	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	10.66	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
433	2271	ARKMUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	12975926.97	4293293.56	3377594.41	\N	3.02	3.84	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	4.89	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
434	2272	AGLDUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1182796.44	460345.22	556724.79	\N	2.57	2.12	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.55	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
435	2272	AGLDUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1472180.74	465974.60	519216.40	\N	3.16	2.84	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	4.69	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
436	2273	YGGUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	7033068.61	2077361.24	2146187.74	\N	3.39	3.28	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	9.93	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
437	2273	YGGUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	6777392.23	2131392.66	2168522.98	\N	3.18	3.13	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.75	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
438	2273	YGGUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	3467291.09	2227392.00	2213559.57	\N	1.56	1.57	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	5.60	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
439	2274	DODOXUSDT	2025-11-01 00:00:00+00	2025-11-01 00:00:00+00	259075.55	165205.17	185986.55	\N	1.57	1.39	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	2.46	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
440	2274	DODOXUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	585729.20	176972.51	177815.38	\N	3.31	3.29	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.46	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
441	2274	DODOXUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	362268.03	197050.07	183909.87	\N	1.84	1.97	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	4.10	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
442	2277	SEIUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	12815060.36	7513625.27	7964122.33	\N	1.71	1.61	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	4.93	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
443	2277	SEIUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	28907967.31	8523120.86	7982575.20	\N	3.39	3.62	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.48	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
444	2277	SEIUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	32025298.76	10563653.23	8715340.55	\N	3.03	3.67	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	9.05	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
445	2278	CYBERUSDT	2025-11-02 04:00:00+00	2025-11-02 04:00:00+00	1174432.61	517900.33	625922.84	\N	2.27	1.88	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	2.16	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
446	2278	CYBERUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1659895.89	555069.93	624573.47	\N	2.99	2.66	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	9.25	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
447	2278	CYBERUSDT	2025-11-04 16:00:00+00	2025-11-04 16:00:00+00	1638548.49	608854.63	631234.94	\N	2.69	2.60	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	8.54	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
448	2278	CYBERUSDT	2025-11-05 12:00:00+00	2025-11-05 12:00:00+00	1122194.21	668119.61	627682.08	\N	1.68	1.79	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	1.83	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
449	2280	ARKUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	604418.12	221112.65	223335.84	\N	2.73	2.71	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.41	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
450	2280	ARKUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	586987.72	251822.56	229618.51	\N	2.33	2.56	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	12.62	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
451	2280	ARKUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	461125.22	259392.69	232674.59	\N	1.78	1.98	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	12.41	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
452	2280	ARKUSDT	2025-11-06 00:00:00+00	2025-11-06 00:00:00+00	1702886.03	262954.67	227263.94	\N	6.48	7.49	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	8.10	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
453	2282	BIGTIMEUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	2940031.28	1021616.79	1207294.43	\N	2.88	2.44	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	5.38	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
454	2284	BSVUSDT	2025-11-01 12:00:00+00	2025-11-01 12:00:00+00	1304057.47	806946.74	568751.48	\N	1.62	2.29	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	3.63	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
455	2284	BSVUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1447027.23	551727.39	587735.68	\N	2.62	2.46	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	14.04	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
456	2284	BSVUSDT	2025-11-04 04:00:00+00	2025-11-04 04:00:00+00	3649848.25	546391.59	605224.66	\N	6.68	6.03	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	10.07	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
457	2284	BSVUSDT	2025-11-05 08:00:00+00	2025-11-05 08:00:00+00	1549334.88	749514.98	707918.75	\N	2.07	2.19	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	9.24	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
458	2286	POLYXUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	1058938.13	256312.16	249404.56	\N	4.13	4.25	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	9.33	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
459	2286	POLYXUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	768781.00	300238.66	270723.00	\N	2.56	2.84	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.10	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
460	2286	POLYXUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	609171.79	310650.30	275697.78	\N	1.96	2.21	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	5.59	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
461	2287	GASUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	362800.65	237913.54	255270.31	\N	1.52	1.42	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	1.74	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
462	2287	GASUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	853471.01	249433.05	254692.22	\N	3.42	3.35	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.39	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
463	2287	GASUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	891535.58	289868.99	265672.25	\N	3.08	3.36	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.64	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
464	2287	GASUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	543041.48	301755.61	271268.17	\N	1.80	2.00	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	8.35	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
465	2288	POWRUSDT	2025-10-31 08:00:00+00	2025-10-31 08:00:00+00	348044.87	174650.48	191259.60	\N	1.99	1.82	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	4.59	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
466	2288	POWRUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	604703.49	195069.83	186692.99	\N	3.10	3.24	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.74	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
467	2288	POWRUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	735379.29	230123.77	200614.15	\N	3.20	3.67	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.65	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
468	2288	POWRUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	601823.16	242043.02	206298.73	\N	2.49	2.92	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	4.52	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
469	2289	TIAUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	23280320.03	12790624.20	14099875.15	\N	1.82	1.65	\N	\N	\N	\N	f	\N	\N	WEAK	30	CONFIRMED	t	10.65	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
470	2289	TIAUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	42715334.03	14495458.72	14155125.21	\N	2.95	3.02	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	9.25	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
471	2289	TIAUSDT	2025-11-04 16:00:00+00	2025-11-04 16:00:00+00	54111561.27	16257819.19	14701978.41	\N	3.33	3.68	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.20	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
472	2290	CAKEUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	11995583.72	7873079.37	11359751.61	\N	1.52	1.06	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	6.54	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
473	2290	CAKEUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	20725584.96	6960889.67	9996586.13	\N	2.98	2.07	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	7.25	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
474	2290	CAKEUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	25143806.35	7720608.19	9137622.62	\N	3.26	2.75	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.83	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
475	2290	CAKEUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	13152577.43	7982482.00	9272957.87	\N	1.65	1.42	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	3.10	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
476	2291	MEMEUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	2983569.83	1826587.38	1818654.66	\N	1.63	1.64	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	1.80	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
477	2291	MEMEUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	9562386.77	2012236.65	1805310.63	\N	4.75	5.30	\N	\N	\N	\N	f	\N	\N	EXTREME	75	CONFIRMED	t	13.24	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
478	2291	MEMEUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	6282552.71	2504209.44	2004139.89	\N	2.51	3.13	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.74	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
479	2292	TWTUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	3114113.73	1906867.07	2184112.84	\N	1.63	1.43	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	3.18	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
480	2292	TWTUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	6378368.45	1960750.04	1920458.88	\N	3.25	3.32	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	7.83	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
481	2292	TWTUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	6493142.77	2294522.43	2044809.91	\N	2.83	3.18	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.45	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
482	2292	TWTUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	3677793.04	2384114.68	2092188.68	\N	1.54	1.76	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	6.50	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
483	2294	ORDIUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	16922933.13	4440952.69	4049376.33	\N	3.81	4.18	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	11.69	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
484	2294	ORDIUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	15855834.33	5397668.82	4443522.01	\N	2.94	3.57	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	5.27	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
485	2295	STEEMUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	346787.39	196395.49	199258.02	\N	1.77	1.74	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	2.44	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
486	2295	STEEMUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	637177.70	235781.95	210909.77	\N	2.70	3.02	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	6.21	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
487	2295	STEEMUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	668559.94	288594.15	234577.51	\N	2.32	2.85	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.99	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
488	2295	STEEMUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	631615.97	296944.57	238711.63	\N	2.13	2.65	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	5.35	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
489	2296	ILVUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	993823.70	442903.82	493044.07	\N	2.24	2.02	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.68	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
490	2296	ILVUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	1206027.84	429203.06	509049.10	\N	2.81	2.37	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	2.99	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
491	2296	ILVUSDT	2025-11-05 00:00:00+00	2025-11-05 00:00:00+00	741834.10	443151.36	518224.95	\N	1.67	1.43	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	2.37	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
492	2297	NTRNUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	460186.81	166137.56	187353.86	\N	2.77	2.46	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	6.52	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
493	2297	NTRNUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	330741.67	177224.70	187282.15	\N	1.87	1.77	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	4.25	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
494	2298	KASUSDT	2025-11-01 08:00:00+00	2025-11-01 08:00:00+00	3525466.00	2153986.70	1967252.36	\N	1.64	1.79	\N	\N	\N	\N	f	\N	\N	WEAK	30	FAILED	t	1.60	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
495	2298	KASUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	5041571.46	1966379.31	1958505.00	\N	2.56	2.57	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	CONFIRMED	t	13.52	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
496	2298	KASUSDT	2025-11-04 20:00:00+00	2025-11-04 20:00:00+00	8101668.43	2269833.40	2057224.58	\N	3.57	3.94	\N	\N	\N	\N	f	\N	\N	STRONG	60	CONFIRMED	t	20.59	\N	t	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
497	2299	BEAMXUSDT	2025-10-31 16:00:00+00	2025-10-31 16:00:00+00	2275380.29	858105.17	977872.13	\N	2.65	2.33	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	3.14	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
498	2299	BEAMXUSDT	2025-11-02 20:00:00+00	2025-11-02 20:00:00+00	2084421.57	982857.19	960349.76	\N	2.12	2.17	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	FAILED	t	1.50	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
499	2299	BEAMXUSDT	2025-11-03 12:00:00+00	2025-11-03 12:00:00+00	3995109.02	1144557.63	1035803.17	\N	3.49	3.86	\N	\N	\N	\N	f	\N	\N	STRONG	60	FAILED	t	8.26	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
500	2299	BEAMXUSDT	2025-11-04 16:00:00+00	2025-11-04 16:00:00+00	6007102.35	1491026.77	1186632.32	\N	4.03	5.06	\N	\N	\N	\N	f	\N	\N	EXTREME	75	FAILED	t	7.57	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 00:27:48.69084+00
1	2115	BTCUSDT	2025-11-07 01:20:09.402734+00	2025-11-07 01:20:09.402734+00	4904556420.66	2394663087.52	2514665014.83	\N	3.50	1.95	\N	\N	\N	\N	f	\N	\N	STRONG	61	MONITORING	t	1.50	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:20:09.402734+00
2	2115	BTCUSDT	2025-11-07 01:20:09.402734+00	2025-11-07 01:20:09.402734+00	5166649806.13	2318932894.05	2386257665.57	\N	4.50	2.17	\N	\N	\N	\N	f	\N	\N	MEDIUM	62	MONITORING	t	3.00	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:20:09.402734+00
3	2115	BTCUSDT	2025-11-07 01:20:09.402734+00	2025-11-07 01:20:09.402734+00	8308118306.74	2572950704.02	2414833151.04	\N	5.50	3.44	\N	\N	\N	\N	f	\N	\N	WEAK	63	MONITORING	t	4.50	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:20:09.402734+00
4	2115	BTCUSDT	2025-11-07 01:20:09.402734+00	2025-11-07 01:20:09.402734+00	5595947232.03	2770056924.47	2464574335.00	\N	6.50	2.27	\N	\N	\N	\N	f	\N	\N	EXTREME	64	MONITORING	t	6.00	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:20:09.402734+00
5	2116	ETHUSDT	2025-11-07 01:20:09.402734+00	2025-11-07 01:20:09.402734+00	5728172299.18	2484482468.74	2492816279.07	\N	2.50	2.30	\N	\N	\N	\N	f	\N	\N	STRONG	65	MONITORING	t	7.50	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:20:09.402734+00
6	2116	ETHUSDT	2025-11-07 01:20:09.402734+00	2025-11-07 01:20:09.402734+00	9988112134.51	2732875836.56	2579210720.27	\N	3.50	3.87	\N	\N	\N	\N	f	\N	\N	MEDIUM	66	MONITORING	t	9.00	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:20:09.402734+00
7	2116	ETHUSDT	2025-11-07 01:20:09.402734+00	2025-11-07 01:20:09.402734+00	4892853820.08	3019160157.61	2696924741.90	\N	4.50	1.81	\N	\N	\N	\N	f	\N	\N	WEAK	67	MONITORING	t	10.50	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:20:09.402734+00
8	2117	BCHUSDT	2025-11-07 01:20:09.402734+00	2025-11-07 01:20:09.402734+00	94225274.99	34181376.98	29022748.45	\N	5.50	3.25	\N	\N	\N	\N	f	\N	\N	EXTREME	68	MONITORING	t	12.00	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:20:09.402734+00
9	2117	BCHUSDT	2025-11-07 01:20:09.402734+00	2025-11-07 01:20:09.402734+00	67754612.89	32714728.48	30002508.03	\N	6.50	2.26	\N	\N	\N	\N	f	\N	\N	STRONG	69	MONITORING	t	13.50	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:20:09.402734+00
10	2117	BCHUSDT	2025-11-07 01:20:09.402734+00	2025-11-07 01:20:09.402734+00	64088091.42	33038083.51	30720697.87	\N	2.50	2.09	\N	\N	\N	\N	f	\N	\N	MEDIUM	70	MONITORING	t	0.00	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:20:09.402734+00
11	2118	XRPUSDT	2025-11-06 21:09:04.900332+00	2025-11-06 22:39:43.164828+00	493748306.95	281035603.18	250469938.88	\N	1.76	1.97	\N	\N	\N	\N	f	\N	\N	WEAK	30	MONITORING	t	1.30	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
12	2118	XRPUSDT	2025-11-06 22:40:05.151665+00	2025-11-07 02:06:19.4134+00	655490874.17	264106624.78	252828277.74	\N	2.48	2.59	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	4.37	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
13	2118	XRPUSDT	2025-11-06 09:13:33.392596+00	2025-11-06 13:08:05.374061+00	939271183.53	298561933.23	269903081.01	\N	3.15	3.48	\N	\N	\N	\N	f	\N	\N	STRONG	60	MONITORING	t	9.62	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
14	2118	XRPUSDT	2025-11-06 16:06:25.288966+00	2025-11-06 21:53:13.099871+00	606934343.31	310856908.49	277480115.65	\N	1.95	2.19	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	MONITORING	t	8.04	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
15	2119	LTCUSDT	2025-11-06 10:41:39.6395+00	2025-11-07 00:16:34.174764+00	129085410.71	51861061.95	42162423.92	\N	2.49	3.06	\N	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	5.83	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
16	2119	LTCUSDT	2025-11-06 14:35:11.795521+00	2025-11-06 10:13:27.557444+00	131180324.39	49849583.40	45440157.59	\N	2.63	2.89	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	MONITORING	t	5.59	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
17	2120	TRXUSDT	2025-11-06 22:00:00.84441+00	2025-11-07 01:15:42.196123+00	46147359.52	16409057.10	18925661.57	\N	2.81	2.44	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	MONITORING	t	2.03	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
18	2120	TRXUSDT	2025-11-06 14:14:38.287228+00	2025-11-06 14:51:55.889268+00	50121084.53	18409805.45	20077556.45	\N	2.72	2.50	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	4.35	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
19	2120	TRXUSDT	2025-11-07 01:13:20.270579+00	2025-11-06 19:14:01.365076+00	41250407.86	21125883.21	21261127.11	\N	1.95	1.94	\N	\N	\N	\N	f	\N	\N	WEAK	30	MONITORING	t	1.53	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
20	2121	ETCUSDT	2025-11-06 12:26:01.233101+00	2025-11-06 15:41:17.454246+00	20073396.62	11123727.75	12403162.07	\N	1.80	1.62	\N	\N	\N	\N	f	\N	\N	WEAK	30	MONITORING	t	3.92	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
21	2121	ETCUSDT	2025-11-06 10:52:45.627605+00	2025-11-06 16:17:40.490287+00	37673372.01	11728355.72	11962593.81	\N	3.21	3.15	\N	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	5.21	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
22	2121	ETCUSDT	2025-11-06 18:20:43.138563+00	2025-11-06 23:01:05.249055+00	44603918.63	14385422.27	12598919.12	\N	3.10	3.54	\N	\N	\N	\N	f	\N	\N	STRONG	60	MONITORING	t	3.39	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
23	2121	ETCUSDT	2025-11-06 23:06:18.076251+00	2025-11-06 11:35:35.911621+00	27539023.04	15026562.87	12891865.66	\N	1.83	2.14	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	MONITORING	t	1.23	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
24	2122	LINKUSDT	2025-11-06 13:08:56.758904+00	2025-11-06 14:28:50.606563+00	198043531.34	64287551.49	63428156.09	\N	3.08	3.12	\N	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	6.83	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
25	2122	LINKUSDT	2025-11-06 11:22:19.219411+00	2025-11-06 11:35:26.77411+00	175039260.81	73640838.52	63960990.37	\N	2.38	2.74	\N	\N	\N	\N	f	\N	\N	MEDIUM	45	MONITORING	t	4.90	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
26	2123	XLMUSDT	2025-11-06 19:39:46.418685+00	2025-11-06 09:01:47.177836+00	46934618.54	12691979.98	12360627.41	\N	3.70	3.80	\N	\N	\N	\N	f	\N	\N	STRONG	60	MONITORING	t	5.44	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
27	2123	XLMUSDT	2025-11-06 20:04:31.060288+00	2025-11-07 02:54:42.749551+00	52370161.69	14368643.47	13291767.19	\N	3.64	3.94	\N	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	4.75	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
28	2123	XLMUSDT	2025-11-07 02:36:57.442925+00	2025-11-06 19:20:25.993154+00	24797543.64	15049743.91	13725255.50	\N	1.65	1.81	\N	\N	\N	\N	f	\N	\N	WEAK	30	MONITORING	t	2.95	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
29	2124	ADAUSDT	2025-11-07 01:31:30.0793+00	2025-11-06 14:55:50.789685+00	180327434.21	57103411.47	53139336.40	\N	3.16	3.39	\N	\N	\N	\N	f	\N	\N	STRONG	60	MONITORING	t	5.45	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
30	2124	ADAUSDT	2025-11-06 15:32:01.621289+00	2025-11-06 14:49:10.872389+00	206653914.75	65659546.76	57115483.90	\N	3.15	3.62	\N	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	5.65	\N	f	VOLUME_SPIKE	2025-11-07 00:27:48.69084+00	2025-11-07 03:21:38.938625+00
501	2161	STORJUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	15693364.89	966900.37	774102.31	1113506.21	16.23	20.27	14.09	\N	\N	\N	f	\N	\N	EXTREME	75	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
502	2426	HIPPOUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	169777448.31	12124493.90	8073134.31	4699942.20	14.00	21.03	36.12	\N	\N	\N	f	\N	\N	EXTREME	75	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
503	2342	METISUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	12189407.08	1041124.20	784536.40	854504.91	11.71	15.54	14.26	\N	\N	\N	f	\N	\N	EXTREME	75	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
504	2169	FILUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	428744349.07	46491326.92	32743363.94	31580865.22	9.22	13.09	13.58	\N	\N	\N	f	\N	\N	EXTREME	75	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
505	2215	DUSKUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	13254445.30	1880887.92	1107560.91	930278.78	7.05	11.97	14.25	\N	\N	\N	f	\N	\N	EXTREME	75	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
506	1013326	AIAUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	391689742.54	65128086.96	42259729.09	48900879.57	6.01	9.27	8.01	\N	\N	\N	f	\N	\N	EXTREME	75	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
507	2572	1000000BOBUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	1872060.82	324585.77	265274.59	326576.28	5.77	7.06	5.73	\N	\N	\N	f	\N	\N	EXTREME	75	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
508	1013342	HANAUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	11300782.53	2286829.34	2922576.31	9634093.32	4.94	3.87	1.17	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
509	933431	ETHWUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	1339468.47	275337.69	220690.32	271522.34	4.86	6.07	4.93	\N	\N	\N	f	\N	\N	EXTREME	75	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
510	2208	ARUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	50167531.16	10500986.14	7040769.68	5113126.49	4.78	7.13	9.81	\N	\N	\N	f	\N	\N	EXTREME	75	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
511	2128	XTZUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	14696941.74	3343403.27	2378917.26	2336057.67	4.40	6.18	6.29	\N	\N	\N	f	\N	\N	EXTREME	75	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
512	2121	ETCUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	63403037.04	14724025.55	12886902.93	19098083.57	4.31	4.92	3.32	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
513	2565	AUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	7173087.15	1682560.19	1315501.80	1605143.90	4.26	5.45	4.47	\N	\N	\N	f	\N	\N	EXTREME	75	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
514	2515	PARTIUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	3556277.02	871688.51	752174.39	1027411.89	4.08	4.73	3.46	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
515	2214	ROSEUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	17293319.17	4401319.00	2768924.52	2461000.43	3.93	6.25	7.03	\N	\N	\N	f	\N	\N	EXTREME	75	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
516	2526	PROMPTUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	15836535.15	4497177.37	2474334.63	1568932.30	3.52	6.40	10.09	\N	\N	\N	f	\N	\N	EXTREME	75	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
517	2231	APTUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	66434736.51	20488681.54	18843114.32	24829603.97	3.24	3.53	2.68	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
518	2509	BROCCOLIF3BUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	2113110.59	692756.44	633447.81	3053664.28	3.05	3.34	0.69	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
519	2557	SKYAIUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	2917332.82	972721.75	880567.98	5881321.18	3.00	3.31	0.50	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
520	2298	KASUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	6907465.54	2423685.57	2231886.52	2986202.37	2.85	3.09	2.31	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
521	2178	1INCHUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	13200372.03	4640905.34	2698591.05	2093381.05	2.84	4.89	6.31	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
522	933290	ENJUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	2245601.08	796375.40	643485.43	819794.16	2.82	3.49	2.74	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
523	2225	STGUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	1972196.11	746499.92	561347.89	781503.32	2.64	3.51	2.52	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
524	2167	NEARUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	72125262.22	28160770.11	24860947.66	31516122.07	2.56	2.90	2.29	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
525	2460	HIVEUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	574408.07	229382.89	209135.41	346083.27	2.50	2.75	1.66	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
526	2546	HAEDALUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	2504563.14	1020742.23	808189.44	799091.37	2.45	3.10	3.13	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
527	2536	DEEPUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	2255597.00	919537.82	772530.33	947869.34	2.45	2.92	2.38	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
528	2336	GLMUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	2795487.45	1145410.10	781154.37	862337.11	2.44	3.58	3.24	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
529	2233	FETUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	25320915.05	10876768.73	9761238.64	14211508.54	2.33	2.59	1.78	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
530	137450	MYXUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	12242481.67	5400742.23	4684226.65	8100809.68	2.27	2.61	1.51	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
531	1013211	SAPIENUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	101154111.01	44683465.30	27600747.46	14117858.15	2.26	3.66	7.16	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
532	2244	STXUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	4987638.70	2227407.34	1943854.69	2516710.40	2.24	2.57	1.98	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
533	2288	POWRUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	535215.30	239326.05	206268.16	291749.26	2.24	2.59	1.83	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
534	2376	ZROUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	10494129.64	4698607.97	3668090.64	4737599.57	2.23	2.86	2.22	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
535	2442	MOVEUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	3813920.38	1744019.03	1583567.53	1942452.33	2.19	2.41	1.96	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
536	933315	ONEUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	1633431.43	747466.49	673395.29	899878.34	2.19	2.43	1.82	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
537	1007882	CROSSUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	608795.08	286113.49	372074.49	568552.21	2.13	1.64	1.07	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
538	2182	RVNUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	4037398.19	1906633.30	1211991.11	1313010.54	2.12	3.33	3.07	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
539	2151	DOTUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	56585147.79	26903832.09	23638867.24	31526198.75	2.10	2.39	1.79	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
540	2153	YFIUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	2680130.13	1295559.84	1070141.32	1242493.74	2.07	2.50	2.16	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
541	2184	COTIUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	1469436.64	711079.71	638201.35	1043222.17	2.07	2.30	1.41	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
542	933259	BATUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	11362879.65	5767983.74	3779006.23	4106009.95	1.97	3.01	2.77	\N	\N	\N	f	\N	\N	STRONG	60	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
543	2469	ALCHUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	2927765.48	1502567.57	1237290.86	1192558.03	1.95	2.37	2.46	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
544	2179	CHZUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	3072376.20	1610881.41	1401073.76	1837499.80	1.91	2.19	1.67	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
545	2219	GMTUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	2365772.94	1241059.00	1176754.70	1693776.55	1.91	2.01	1.40	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
546	2284	BSVUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	1488277.07	788766.27	777175.18	840005.92	1.89	1.91	1.77	\N	\N	\N	f	\N	\N	WEAK	30	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
547	927662	BULLAUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	365664.76	196159.64	231149.00	246801.92	1.86	1.58	1.48	\N	\N	\N	f	\N	\N	WEAK	30	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
548	2247	CKBUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	1560396.40	841400.77	943479.18	829715.61	1.85	1.65	1.88	\N	\N	\N	f	\N	\N	WEAK	30	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
549	2142	ZRXUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	3631215.97	1960431.82	1459205.40	1420073.60	1.85	2.49	2.56	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
550	2380	RAREUSDT	2025-11-07 03:17:54.058796+00	2025-11-07 00:00:00+00	843519.22	473839.43	438332.60	969179.69	1.78	1.92	0.87	\N	\N	\N	f	\N	\N	WEAK	30	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:17:54.058796+00	2025-11-07 03:17:54.058796+00
551	2246	SSVUSDT	2025-11-07 03:20:01.726533+00	2025-11-07 00:00:00+00	1647466.22	1027274.50	944334.29	1545203.65	1.60	1.74	1.07	\N	\N	\N	f	\N	\N	WEAK	30	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:20:01.726533+00	2025-11-07 03:20:01.726533+00
552	2575	HOMEUSDT	2025-11-07 03:20:01.726533+00	2025-11-07 00:00:00+00	495730.69	322101.04	432366.63	661305.79	1.54	1.15	0.75	\N	\N	\N	f	\N	\N	WEAK	30	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:20:01.726533+00	2025-11-07 03:20:01.726533+00
553	2390	CHESSUSDT	2025-11-07 03:20:01.726533+00	2025-11-07 00:00:00+00	389630.24	254384.34	289712.13	514450.88	1.53	1.34	0.76	\N	\N	\N	f	\N	\N	WEAK	30	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:20:01.726533+00	2025-11-07 03:20:01.726533+00
554	2286	POLYXUSDT	2025-11-07 03:20:01.726533+00	2025-11-07 00:00:00+00	454162.92	296687.17	273688.82	379232.36	1.53	1.66	1.20	\N	\N	\N	f	\N	\N	WEAK	30	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:20:01.726533+00	2025-11-07 03:20:01.726533+00
555	933292	KSMUSDT	2025-11-07 03:20:01.726533+00	2025-11-07 00:00:00+00	3255460.37	2133219.97	1487716.41	1396124.79	1.53	2.19	2.33	\N	\N	\N	f	\N	\N	MEDIUM	45	DETECTED	t	\N	\N	f	VOLUME_SPIKE	2025-11-07 03:20:01.726533+00	2025-11-07 03:20:01.726533+00
\.


--
-- Data for Name: thresholds; Type: TABLE DATA; Schema: pump; Owner: elcrypto
--

COPY pump.thresholds (trading_pair_id, pair_symbol, custom_min_spike, custom_extreme_spike, custom_strong_spike, custom_medium_spike, avg_spike_before_pump, avg_days_to_pump, avg_pump_size_pct, total_signals_count, successful_signals_count, historical_accuracy, is_monitored, requires_spot_sync, min_oi_increase_pct, notes, updated_at) FROM stdin;
\.


--
-- Data for Name: user_watchlist; Type: TABLE DATA; Schema: pump; Owner: elcrypto
--

COPY pump.user_watchlist (id, user_id, trading_pair_id, pair_symbol, min_confidence, notification_types, is_active, created_at) FROM stdin;
\.


--
-- Name: notifications_id_seq; Type: SEQUENCE SET; Schema: pump; Owner: elcrypto
--

SELECT pg_catalog.setval('pump.notifications_id_seq', 1, false);


--
-- Name: patterns_id_seq; Type: SEQUENCE SET; Schema: pump; Owner: elcrypto
--

SELECT pg_catalog.setval('pump.patterns_id_seq', 4, true);


--
-- Name: performance_stats_id_seq; Type: SEQUENCE SET; Schema: pump; Owner: elcrypto
--

SELECT pg_catalog.setval('pump.performance_stats_id_seq', 1, false);


--
-- Name: signal_confirmations_id_seq; Type: SEQUENCE SET; Schema: pump; Owner: elcrypto
--

SELECT pg_catalog.setval('pump.signal_confirmations_id_seq', 1, false);


--
-- Name: signal_tracking_id_seq; Type: SEQUENCE SET; Schema: pump; Owner: elcrypto
--

SELECT pg_catalog.setval('pump.signal_tracking_id_seq', 1, false);


--
-- Name: signals_id_seq; Type: SEQUENCE SET; Schema: pump; Owner: elcrypto
--

SELECT pg_catalog.setval('pump.signals_id_seq', 555, true);


--
-- Name: user_watchlist_id_seq; Type: SEQUENCE SET; Schema: pump; Owner: elcrypto
--

SELECT pg_catalog.setval('pump.user_watchlist_id_seq', 1, false);


--
-- Name: config config_pkey; Type: CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.config
    ADD CONSTRAINT config_pkey PRIMARY KEY (key);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);


--
-- Name: patterns patterns_pattern_name_key; Type: CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.patterns
    ADD CONSTRAINT patterns_pattern_name_key UNIQUE (pattern_name);


--
-- Name: patterns patterns_pkey; Type: CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.patterns
    ADD CONSTRAINT patterns_pkey PRIMARY KEY (id);


--
-- Name: performance_stats performance_stats_pkey; Type: CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.performance_stats
    ADD CONSTRAINT performance_stats_pkey PRIMARY KEY (id);


--
-- Name: performance_stats performance_stats_stat_date_stat_hour_key; Type: CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.performance_stats
    ADD CONSTRAINT performance_stats_stat_date_stat_hour_key UNIQUE (stat_date, stat_hour);


--
-- Name: signal_confirmations signal_confirmations_pkey; Type: CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.signal_confirmations
    ADD CONSTRAINT signal_confirmations_pkey PRIMARY KEY (id);


--
-- Name: signal_scores signal_scores_pkey; Type: CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.signal_scores
    ADD CONSTRAINT signal_scores_pkey PRIMARY KEY (signal_id);


--
-- Name: signal_tracking signal_tracking_pkey; Type: CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.signal_tracking
    ADD CONSTRAINT signal_tracking_pkey PRIMARY KEY (id);


--
-- Name: signals signals_pkey; Type: CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.signals
    ADD CONSTRAINT signals_pkey PRIMARY KEY (id);


--
-- Name: thresholds thresholds_pkey; Type: CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.thresholds
    ADD CONSTRAINT thresholds_pkey PRIMARY KEY (trading_pair_id);


--
-- Name: user_watchlist user_watchlist_pkey; Type: CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.user_watchlist
    ADD CONSTRAINT user_watchlist_pkey PRIMARY KEY (id);


--
-- Name: user_watchlist user_watchlist_user_id_trading_pair_id_key; Type: CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.user_watchlist
    ADD CONSTRAINT user_watchlist_user_id_trading_pair_id_key UNIQUE (user_id, trading_pair_id);


--
-- Name: idx_confirmations_signal; Type: INDEX; Schema: pump; Owner: elcrypto
--

CREATE INDEX idx_confirmations_signal ON pump.signal_confirmations USING btree (signal_id, confirmation_timestamp DESC);


--
-- Name: idx_confirmations_type; Type: INDEX; Schema: pump; Owner: elcrypto
--

CREATE INDEX idx_confirmations_type ON pump.signal_confirmations USING btree (confirmation_type);


--
-- Name: idx_notifications_event; Type: INDEX; Schema: pump; Owner: elcrypto
--

CREATE INDEX idx_notifications_event ON pump.notifications USING btree (notification_event);


--
-- Name: idx_notifications_sent_at; Type: INDEX; Schema: pump; Owner: elcrypto
--

CREATE INDEX idx_notifications_sent_at ON pump.notifications USING btree (sent_at DESC);


--
-- Name: idx_notifications_signal; Type: INDEX; Schema: pump; Owner: elcrypto
--

CREATE INDEX idx_notifications_signal ON pump.notifications USING btree (signal_id);


--
-- Name: idx_signals_confidence; Type: INDEX; Schema: pump; Owner: elcrypto
--

CREATE INDEX idx_signals_confidence ON pump.signals USING btree (initial_confidence DESC) WHERE (is_active = true);


--
-- Name: idx_signals_detected_at; Type: INDEX; Schema: pump; Owner: elcrypto
--

CREATE INDEX idx_signals_detected_at ON pump.signals USING btree (detected_at DESC);


--
-- Name: idx_signals_pair_time; Type: INDEX; Schema: pump; Owner: elcrypto
--

CREATE INDEX idx_signals_pair_time ON pump.signals USING btree (trading_pair_id, signal_timestamp DESC);


--
-- Name: idx_signals_status; Type: INDEX; Schema: pump; Owner: elcrypto
--

CREATE INDEX idx_signals_status ON pump.signals USING btree (status) WHERE (is_active = true);


--
-- Name: idx_signals_strength; Type: INDEX; Schema: pump; Owner: elcrypto
--

CREATE INDEX idx_signals_strength ON pump.signals USING btree (signal_strength, detected_at DESC);


--
-- Name: idx_tracking_signal_time; Type: INDEX; Schema: pump; Owner: elcrypto
--

CREATE INDEX idx_tracking_signal_time ON pump.signal_tracking USING btree (signal_id, tracking_timestamp DESC);


--
-- Name: idx_tracking_timestamp; Type: INDEX; Schema: pump; Owner: elcrypto
--

CREATE INDEX idx_tracking_timestamp ON pump.signal_tracking USING btree (tracking_timestamp DESC);


--
-- Name: config update_config_updated_at; Type: TRIGGER; Schema: pump; Owner: elcrypto
--

CREATE TRIGGER update_config_updated_at BEFORE UPDATE ON pump.config FOR EACH ROW EXECUTE FUNCTION pump.update_updated_at_column();


--
-- Name: signal_scores update_scores_updated_at; Type: TRIGGER; Schema: pump; Owner: elcrypto
--

CREATE TRIGGER update_scores_updated_at BEFORE UPDATE ON pump.signal_scores FOR EACH ROW EXECUTE FUNCTION pump.update_updated_at_column();


--
-- Name: signals update_signals_updated_at; Type: TRIGGER; Schema: pump; Owner: elcrypto
--

CREATE TRIGGER update_signals_updated_at BEFORE UPDATE ON pump.signals FOR EACH ROW EXECUTE FUNCTION pump.update_updated_at_column();


--
-- Name: notifications notifications_signal_id_fkey; Type: FK CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.notifications
    ADD CONSTRAINT notifications_signal_id_fkey FOREIGN KEY (signal_id) REFERENCES pump.signals(id) ON DELETE CASCADE;


--
-- Name: signal_confirmations signal_confirmations_signal_id_fkey; Type: FK CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.signal_confirmations
    ADD CONSTRAINT signal_confirmations_signal_id_fkey FOREIGN KEY (signal_id) REFERENCES pump.signals(id) ON DELETE CASCADE;


--
-- Name: signal_scores signal_scores_signal_id_fkey; Type: FK CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.signal_scores
    ADD CONSTRAINT signal_scores_signal_id_fkey FOREIGN KEY (signal_id) REFERENCES pump.signals(id) ON DELETE CASCADE;


--
-- Name: signal_tracking signal_tracking_signal_id_fkey; Type: FK CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.signal_tracking
    ADD CONSTRAINT signal_tracking_signal_id_fkey FOREIGN KEY (signal_id) REFERENCES pump.signals(id) ON DELETE CASCADE;


--
-- Name: signals signals_trading_pair_id_fkey; Type: FK CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.signals
    ADD CONSTRAINT signals_trading_pair_id_fkey FOREIGN KEY (trading_pair_id) REFERENCES public.trading_pairs(id);


--
-- Name: thresholds thresholds_trading_pair_id_fkey; Type: FK CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.thresholds
    ADD CONSTRAINT thresholds_trading_pair_id_fkey FOREIGN KEY (trading_pair_id) REFERENCES public.trading_pairs(id);


--
-- Name: user_watchlist user_watchlist_trading_pair_id_fkey; Type: FK CONSTRAINT; Schema: pump; Owner: elcrypto
--

ALTER TABLE ONLY pump.user_watchlist
    ADD CONSTRAINT user_watchlist_trading_pair_id_fkey FOREIGN KEY (trading_pair_id) REFERENCES public.trading_pairs(id);


--
-- PostgreSQL database dump complete
--

\unrestrict pqchlHNTG8b5gASfLjnETgdQUzb7CtwDJH2M7oQZpLh0d7aJctDcASTWjqpV4QT

