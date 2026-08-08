-- Three systems. Each issues its own key, and each ALSO carries foreign keys to the
-- others, which is the crux: a column holding another system's ID is not identity.
CREATE TABLE SFDC_ACCOUNT (
    ACCOUNT_ID   VARCHAR(18) NOT NULL PRIMARY KEY,  -- SFDC 18-char id
    ACCOUNT_NAME VARCHAR(200),
    ERP_ID__C    VARCHAR(40),                       -- ERP's key, carried by SFDC
    BILLING_ID__C VARCHAR(40),                      -- Billing's key, carried by SFDC
    BILLING_ST   VARCHAR(2),
    BILLING_ZIP  VARCHAR(10)
);
CREATE TABLE SFDC_OPPORTUNITY (
    OPPORTUNITY_ID VARCHAR(18) NOT NULL PRIMARY KEY,
    ACCOUNT_ID     VARCHAR(18) NOT NULL,            -- FK to SFDC_ACCOUNT
    NAME           VARCHAR(200),
    AMOUNT         NUMBER(18,2)
);
CREATE TABLE ERP_CUSTOMER (
    COMPANY_CODE VARCHAR(4)  NOT NULL,              -- composite key, part 1
    CUSTOMER_NO  VARCHAR(20) NOT NULL,              -- composite key, part 2
    NAME1        VARCHAR(200),
    REGION       VARCHAR(2),
    POSTAL_CODE  VARCHAR(10),
    PRIMARY KEY (COMPANY_CODE, CUSTOMER_NO)
);
CREATE TABLE BILLING_PARTY (
    PARTY_ID    VARCHAR(40) NOT NULL PRIMARY KEY,
    PARTY_NAME  VARCHAR(200),
    ERP_REF     VARCHAR(40),                        -- ERP's key, carried by Billing
    STATE_CODE  VARCHAR(2),
    ZIP         VARCHAR(10)
);
