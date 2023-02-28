--
-- PostgreSQL database dump
--

-- Dumped from database version 12.2 (Ubuntu 12.2-4)
-- Dumped by pg_dump version 12.2 (Ubuntu 12.2-4)

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
-- IMPORTANT ###################################
-- THIS MUST BE RUN WHILE CONNECTED TO THE HOTQUEUE DATABASE
-- THIS SWITCHES ON THE UUID FUNCTIONS
--
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

--
-- Name: notify_messagequeue(); Type: FUNCTION; Schema: public; Owner: hotqueue_user
--

CREATE FUNCTION public.notify_messagequeue() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
BEGIN
  PERFORM pg_notify(CAST('message_queue' AS text), json_build_object('queuename',NEW.queuename,'message_id',CAST(NEW.id AS text))::text);
  RETURN NEW;
END;
$$;


ALTER FUNCTION public.notify_messagequeue() OWNER TO hotqueue_user;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: message_queue; Type: TABLE; Schema: public; Owner: hotqueue_user
--

CREATE TABLE public.message_queue (
    id bigint NOT NULL,
    messagebody jsonb,
    status text DEFAULT 'new'::text,
    created timestamp without time zone DEFAULT now(),
    queuename text DEFAULT ''::text NOT NULL,
    priority integer DEFAULT 100 NOT NULL,
    visibility timestamp without time zone DEFAULT now(),
    messagegroupid text,
    accountid text
);


ALTER TABLE public.message_queue OWNER TO hotqueue_user;

--
-- Name: message_queue_id_seq; Type: SEQUENCE; Schema: public; Owner: hotqueue_user
--

CREATE SEQUENCE public.message_queue_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.message_queue_id_seq OWNER TO hotqueue_user;

--
-- Name: message_queue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: hotqueue_user
--

ALTER SEQUENCE public.message_queue_id_seq OWNED BY public.message_queue.id;


--
-- Name: message_queue id; Type: DEFAULT; Schema: public; Owner: hotqueue_user
--

ALTER TABLE ONLY public.message_queue ALTER COLUMN id SET DEFAULT nextval('public.message_queue_id_seq'::regclass);


--
-- Name: message_queue message_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: hotqueue_user
--

ALTER TABLE ONLY public.message_queue
    ADD CONSTRAINT message_queue_pkey PRIMARY KEY (id);


--
-- Name: message_queue notify_messagequeue; Type: TRIGGER; Schema: public; Owner: hotqueue_user
--

CREATE TRIGGER notify_messagequeue AFTER INSERT ON public.message_queue FOR EACH ROW EXECUTE FUNCTION public.notify_messagequeue();


--
-- PostgreSQL database dump complete
--

