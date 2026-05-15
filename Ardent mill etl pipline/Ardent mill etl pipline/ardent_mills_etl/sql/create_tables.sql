-- =============================================================================
-- Ardent Mills ETL — Oracle DDL
-- Run once to create all target tables.
-- Tables are ordered to respect FK dependencies.
-- =============================================================================

-- ── Dimension tables ──────────────────────────────────────────────────────────

CREATE TABLE ARD_OPS_SITE (
    site_id         NUMBER(10)    NOT NULL,
    site_name       VARCHAR2(200),
    ops_type        VARCHAR2(100),
    region          VARCHAR2(100),
    pack_plant      VARCHAR2(100),
    company         VARCHAR2(100),
    country_cd      VARCHAR2(10),
    created_date    DATE,
    created_by      VARCHAR2(100),
    updated_date    DATE,
    updated_by      VARCHAR2(100),
    CONSTRAINT pk_ard_site PRIMARY KEY (site_id)
);

CREATE TABLE ARD_OPS_ITEMCLASS (
    item_class_id   NUMBER(10)    NOT NULL,
    item_class_desc VARCHAR2(200),
    created_date    DATE,
    created_by      VARCHAR2(100),
    updated_date    DATE,
    updated_by      VARCHAR2(100),
    CONSTRAINT pk_ard_itemclass PRIMARY KEY (item_class_id)
);

CREATE TABLE ARD_OPS_PRODUCT (
    product_pk      NUMBER(10)    GENERATED ALWAYS AS IDENTITY,
    product_id      VARCHAR2(100) NOT NULL,
    product_desc    VARCHAR2(500),
    item_class_id   NUMBER(10),
    created_date    DATE,
    created_by      VARCHAR2(100),
    updated_date    DATE,
    updated_by      VARCHAR2(100),
    CONSTRAINT pk_ard_product    PRIMARY KEY (product_pk),
    CONSTRAINT uq_ard_product_id UNIQUE      (product_id),
    CONSTRAINT fk_product_class  FOREIGN KEY (item_class_id) REFERENCES ARD_OPS_ITEMCLASS(item_class_id)
);

CREATE TABLE ARD_OPS_CUSTOMER (
    customer_id     NUMBER(10)    NOT NULL,
    customer_nm     VARCHAR2(500),
    created_date    DATE,
    created_by      VARCHAR2(100),
    updated_date    DATE,
    updated_by      VARCHAR2(100),
    CONSTRAINT pk_ard_customer PRIMARY KEY (customer_id)
);

CREATE TABLE ARD_OPS_SHIPTOACCOUNT (
    ship_to_id      NUMBER(10)    NOT NULL,
    ship_to_name    VARCHAR2(500),
    sold_to_name    VARCHAR2(500),
    city            VARCHAR2(200),
    state           VARCHAR2(100),
    zip             VARCHAR2(20),
    country         VARCHAR2(100),
    created_date    DATE,
    created_by      VARCHAR2(100),
    updated_date    DATE,
    updated_by      VARCHAR2(100),
    CONSTRAINT pk_ard_shipto PRIMARY KEY (ship_to_id)
);

CREATE TABLE ARD_OPS_CARRIER (
    carrier_id      NUMBER(10)    NOT NULL,
    carrier_code    VARCHAR2(100),
    created_date    DATE,
    created_by      VARCHAR2(100),
    updated_date    DATE,
    updated_by      VARCHAR2(100),
    CONSTRAINT pk_ard_carrier PRIMARY KEY (carrier_id)
);

CREATE TABLE ARD_OPS_PRODUCTIONMIX (
    production_mix_id   NUMBER(10)    NOT NULL,
    production_mix_code VARCHAR2(200),
    created_date        DATE,
    created_by          VARCHAR2(100),
    updated_date        DATE,
    updated_by          VARCHAR2(100),
    CONSTRAINT pk_ard_prodmix PRIMARY KEY (production_mix_id)
);

CREATE TABLE ARD_OPS_MAINTENANCETYPE (
    maintenance_type_id NUMBER(10)    NOT NULL,
    maintenance_type    VARCHAR2(200),
    created_date        DATE,
    created_by          VARCHAR2(100),
    updated_date        DATE,
    updated_by          VARCHAR2(100),
    CONSTRAINT pk_ard_maint PRIMARY KEY (maintenance_type_id)
);

CREATE TABLE ARD_OPS_CLEANINGTYPE (
    cleaning_type_pk    NUMBER(10)    GENERATED ALWAYS AS IDENTITY,
    cleaning_type_id    VARCHAR2(100) NOT NULL,
    cleaning_type_desc  VARCHAR2(200),
    created_date        DATE,
    created_by          VARCHAR2(100),
    updated_date        DATE,
    updated_by          VARCHAR2(100),
    CONSTRAINT pk_ard_cleantype    PRIMARY KEY (cleaning_type_pk),
    CONSTRAINT uq_ard_cleantype_id UNIQUE      (cleaning_type_id)
);

CREATE TABLE ARD_OPS_PACKLINE (
    line_id         NUMBER(10)    NOT NULL,
    line_name       VARCHAR2(200),
    site_id         NUMBER(10),
    created_date    DATE,
    created_by      VARCHAR2(100),
    updated_date    DATE,
    updated_by      VARCHAR2(100),
    CONSTRAINT pk_ard_packline    PRIMARY KEY (line_id),
    CONSTRAINT fk_packline_site   FOREIGN KEY (site_id) REFERENCES ARD_OPS_SITE(site_id)
);

CREATE TABLE ARD_OPS_BIN (
    bin_pk          NUMBER(10)    GENERATED ALWAYS AS IDENTITY,
    bin_id          VARCHAR2(100) NOT NULL,
    bin_purpose     VARCHAR2(200),
    site_id         NUMBER(10),
    created_date    DATE,
    created_by      VARCHAR2(100),
    updated_date    DATE,
    updated_by      VARCHAR2(100),
    CONSTRAINT pk_ard_bin      PRIMARY KEY (bin_pk),
    CONSTRAINT uq_ard_bin_id   UNIQUE      (bin_id),
    CONSTRAINT fk_bin_site     FOREIGN KEY (site_id) REFERENCES ARD_OPS_SITE(site_id)
);

-- ── Fact / transaction tables ─────────────────────────────────────────────────

CREATE TABLE ARD_OPS_PACKRUN (
    pack_run_id     NUMBER(10)    NOT NULL,
    site_id         NUMBER(10),
    product_id      VARCHAR2(100),
    line_id         NUMBER(10),
    pack_date       DATE,
    good_units      NUMBER(18,4),
    target_units    NUMBER(18,4),
    total_units     NUMBER(10),
    calc_dt         NUMBER(18,4),
    minutes_run     NUMBER(18,4),
    pack_oee        NUMBER(18,6),
    created_date    DATE,
    created_by      VARCHAR2(100),
    updated_date    DATE,
    updated_by      VARCHAR2(100),
    CONSTRAINT pk_ard_packrun   PRIMARY KEY (pack_run_id),
    CONSTRAINT fk_pr_site       FOREIGN KEY (site_id)   REFERENCES ARD_OPS_SITE(site_id),
    CONSTRAINT fk_pr_line       FOREIGN KEY (line_id)   REFERENCES ARD_OPS_PACKLINE(line_id)
);

CREATE TABLE ARD_OPS_MILLRUN (
    mill_run_id         NUMBER(10)    NOT NULL,
    site_id             NUMBER(10),
    mill_date           DATE,
    unit                VARCHAR2(100),
    production_mix_id   NUMBER(10),
    calc_downtime       NUMBER(18,4),
    min_run             NUMBER(18,4),
    no_demand_downtime  NUMBER(18,4),
    mill_oee            NUMBER(18,6),
    created_date        DATE,
    created_by          VARCHAR2(100),
    updated_date        DATE,
    updated_by          VARCHAR2(100),
    CONSTRAINT pk_ard_millrun    PRIMARY KEY (mill_run_id),
    CONSTRAINT fk_mr_site        FOREIGN KEY (site_id)           REFERENCES ARD_OPS_SITE(site_id),
    CONSTRAINT fk_mr_prodmix     FOREIGN KEY (production_mix_id) REFERENCES ARD_OPS_PRODUCTIONMIX(production_mix_id)
);

CREATE TABLE ARD_OPS_SALESORDER (
    order_id        NUMBER(10)    NOT NULL,
    order_no        VARCHAR2(100),
    site_id         NUMBER(10),
    customer_id     NUMBER(10),
    ship_date       DATE,
    order_status    VARCHAR2(50),
    created_date    DATE,
    created_by      VARCHAR2(100),
    updated_date    DATE,
    updated_by      VARCHAR2(100),
    CONSTRAINT pk_ard_salesorder   PRIMARY KEY (order_id),
    CONSTRAINT uq_ard_order_no     UNIQUE      (order_no),
    CONSTRAINT fk_so_site          FOREIGN KEY (site_id)     REFERENCES ARD_OPS_SITE(site_id),
    CONSTRAINT fk_so_customer      FOREIGN KEY (customer_id) REFERENCES ARD_OPS_CUSTOMER(customer_id)
);

CREATE TABLE ARD_OPS_SALESORDERLINE (
    order_line_id   NUMBER(10)    NOT NULL,
    order_no        VARCHAR2(100),
    product_id      VARCHAR2(100),
    invoice_cwts    NUMBER(18,4),
    created_date    DATE,
    created_by      VARCHAR2(100),
    updated_date    DATE,
    updated_by      VARCHAR2(100),
    CONSTRAINT pk_ard_solline PRIMARY KEY (order_line_id)
);

CREATE TABLE ARD_OPS_WORKORDER (
    workorder_pk                NUMBER(10)    GENERATED ALWAYS AS IDENTITY,
    wo_no                       VARCHAR2(100) NOT NULL,
    site_id                     NUMBER(10),
    maintenance_type_id         NUMBER(10),
    category_cd                 VARCHAR2(100),
    status_cd                   VARCHAR2(50),
    preventive_corrective_ind   VARCHAR2(10),
    late_indicator              VARCHAR2(10),
    required_date               DATE,
    wo_count                    NUMBER(10),
    wo_late_count               NUMBER(10),
    wo_ontime_count             NUMBER(10),
    wo_upcoming_count           NUMBER(10),
    created_date                DATE,
    created_by                  VARCHAR2(100),
    updated_date                DATE,
    updated_by                  VARCHAR2(100),
    CONSTRAINT pk_ard_workorder   PRIMARY KEY (workorder_pk),
    CONSTRAINT uq_ard_wo_no       UNIQUE      (wo_no),
    CONSTRAINT fk_wo_site         FOREIGN KEY (site_id)             REFERENCES ARD_OPS_SITE(site_id),
    CONSTRAINT fk_wo_maint        FOREIGN KEY (maintenance_type_id) REFERENCES ARD_OPS_MAINTENANCETYPE(maintenance_type_id)
);

CREATE TABLE ARD_OPS_BINCLEANINGLOG (
    cleaning_log_id         NUMBER(10)    NOT NULL,
    bin_id                  VARCHAR2(100),
    cleaning_type_id        VARCHAR2(100),
    cleaning_completed_on   DATE,
    cleaning_completed_by   VARCHAR2(200),
    days_since_last_cleaning NUMBER(10),
    bin_status              VARCHAR2(100),
    clean_standard_in_place NUMBER(10),
    clean_standard_freq     NUMBER(10),
    comments                VARCHAR2(2000),
    last_refresh_time       DATE,
    status_as_of_date       DATE,
    status_as_of_wk_start   DATE,
    created_date            DATE,
    created_by              VARCHAR2(100),
    updated_date            DATE,
    updated_by              VARCHAR2(100),
    CONSTRAINT pk_ard_bincleaning PRIMARY KEY (cleaning_log_id)
);

CREATE TABLE ARD_OPS_FILLORDER (
    fill_order_id       NUMBER(10)    NOT NULL,
    order_number        NUMBER(10),
    vessel_id           NUMBER(10),
    site_id             NUMBER(10),
    ship_to_id          NUMBER(10),
    carrier_id          NUMBER(10),
    product_id          VARCHAR2(100),
    bulk_or_sack        VARCHAR2(50),
    miles               NUMBER(10),
    drop_ship           VARCHAR2(10),
    modifier            VARCHAR2(100),
    delivery_note_no    NUMBER(10),
    load_date           DATE,
    ship_date           DATE,
    released_date       DATE,
    shipped_cwt         NUMBER(18,4),
    volume              NUMBER(18,4),
    site_goal           NUMBER(10),
    site_max            NUMBER(10),
    exception_cwts      NUMBER(18,4),
    baseline            NUMBER(18,4),
    max_for_load        NUMBER(18,4),
    goal_for_load       NUMBER(18,4),
    made_goal           NUMBER(10),
    var_to_goal         NUMBER(18,4),
    var_to_baseline     NUMBER(18,4),
    var_to_load_max     NUMBER(18,4),
    var_to_site_max     NUMBER(18,4),
    excluded            VARCHAR2(10),
    exception_flag      VARCHAR2(10),
    created_date        DATE,
    created_by          VARCHAR2(100),
    updated_date        DATE,
    updated_by          VARCHAR2(100),
    CONSTRAINT pk_ard_fillorder  PRIMARY KEY (fill_order_id),
    CONSTRAINT fk_fo_site        FOREIGN KEY (site_id)    REFERENCES ARD_OPS_SITE(site_id),
    CONSTRAINT fk_fo_shipto      FOREIGN KEY (ship_to_id) REFERENCES ARD_OPS_SHIPTOACCOUNT(ship_to_id),
    CONSTRAINT fk_fo_carrier     FOREIGN KEY (carrier_id) REFERENCES ARD_OPS_CARRIER(carrier_id)
);
