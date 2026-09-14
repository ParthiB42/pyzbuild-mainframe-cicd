
# ═══════════════════════════ PyZBuild v0.1  ═══════════════════════════  #

"""

🚀 Python-based z/OS COBOL/CICS/DB2 build automation using z/OSMF REST APIs. 🚀

 Workflow:
*---------*
    1. Load configuration from .env
    2. Validate configuration
    3. Authenticate with z/OSMF
    4. Analyze the COBOL source type (Batch/CICS/DB2)
    4. Upload COBOL source to respective SRCLIB
    5. Generate compile JCL based on the COBOL source type
    6. Submit JCL through z/OSMF
    7. Monitor JES job
    8. Evaluate final return code
    9. Send the return code/Responce back to jenkins Job.

Build policy:
*-----------*
    RC 0000  -> SUCCESS  ✅
    RC 0004  -> SUCCESS WITH WARNINGS ‼️
    RC 0008+ -> FAILURE  ❌

"""

#----------------------*
#   Fundamentals       *
#----------------------*  

from pathlib import Path
from typing  import Any
from dotenv  import load_dotenv
from requests.auth import HTTPBasicAuth

#----------------------*
#   Needed Modules     *
#----------------------* 

import argparse
import os
import re
import sys
import time
import requests
import urllib3
import sys

#----------------------* 
#   PROJECT / .ENV     *
#----------------------* 

PROJECT_DIR = Path(__file__).resolve().parent        

ENV_FILE    = PROJECT_DIR / ".env"

#----------------------*
#   Load .env file     *
#----------------------*

load_dotenv(dotenv_path=ENV_FILE,                            #---> Load .env file
            override=True)

#------------------------------------------------*
#   Load Mainframe User Details from .env file   *
#------------------------------------------------*

HOST     = os.getenv("ZOSMF_HOST")
PORT_RAW = os.getenv("ZOSMF_PORT")
ZOSUSER  = os.getenv("ZOSMF_USERNAME")
PASSWORD = os.getenv("ZOSMF_PASSWORD")

#-----------------------------------------------------*  
#   Disable SSL warning for self-signed certificate   *   
#-----------------------------------------------------* 

VERIFY_SSL = (os.getenv("ZOSMF_VERIFY_SSL","false").lower()== "true")

if not VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

#-----------------------------------*
#   Load Libraries from .env file   *
#-----------------------------------*

JCLLIB       = os.getenv("JCLLIB")
SRCLIB       = os.getenv("SRCLIB")
CICS_SRCLIB  = os.getenv("CICS_SRCLIB")
DB2_SRCLIB   = os.getenv("DB2_SRCLIB")
COPYLIB      = os.getenv("COPYLIB")
LOADLIB      = os.getenv("LOADLIB")
OBJLIB       = os.getenv("OBJLIB")

#----------------------------------------*
#   Load Configurations from .env file   *
#----------------------------------------*

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT","30"))
BUILD_TIMEOUT   = int(os.getenv("BUILD_TIMEOUT","1800"))
POLL_INTERVAL   = int(os.getenv("POLL_INTERVAL","2"))

#--------------------------------*
#   Set Acceptable Return Code   *
#--------------------------------*

def load_acceptable_rcs() -> set[int]:                 

    raw = os.getenv("ACCEPTABLE_RC", "0,4")

    acceptable: set[int] = set()

    for value in raw.split(","):

        value = value.strip()

        if not value:
            continue

        try:
            acceptable.add(int(value))

        except ValueError as exc:
            raise ValueError("Invalid return code in " f"ACCEPTABLE_RC: {value}") from exc

    return acceptable

#--------------------------------------*
#   Call load_acceptable_rcs           *
#   Store the data in ACCEPTABLE_RCS   *
#--------------------------------------*

ACCEPTABLE_RCS = load_acceptable_rcs()

#----------------*
#   Exception    *
#----------------*

class PyZBuildError(RuntimeError):

 """Expected PyZBuild error."""

#------------------*
#   HTTP Session   *
#------------------*

session = requests.Session()

def configure_session() -> None:

    """
    Configure one persistent HTTP session.

    The same session is used for:

        # /zosmf/info
        # /restfiles
        # /restjobs
        # job monitoring

    This allows cookies such as LtpaToken2 returned by z/OSMF to be maintained automatically.

    """
 
    if not ZOSUSER:         
        raise PyZBuildError("ZOSMF_USERNAME is not configured.")              

    if not PASSWORD:
        raise PyZBuildError("ZOSMF_PASSWORD is not configured.")

    session.auth   = HTTPBasicAuth(ZOSUSER, PASSWORD)  

    session.verify = VERIFY_SSL

    session.headers.update({"X-CSRF-ZOSMF-HEADER": "*"})

#----------------------------------------*
#    Mainframe User Details Validation   *
#----------------------------------------*

def validate_environment() -> None:

    missing: list[str] = []

    if not HOST:
        missing.append("ZOSMF_HOST")

    if not PORT_RAW:
        missing.append("ZOSMF_PORT")

    if not ZOSUSER:
        missing.append("ZOSMF_USERNAME")

    if not PASSWORD:
        missing.append("ZOSMF_PASSWORD")

#---------------------------*
#    Libraries Validation   *
#---------------------------*

    if not JCLLIB:
        missing.append("JCLLIB")

    if not SRCLIB:
        missing.append("SRCLIB")

    if not CICS_SRCLIB:
        missing.append("CICS_SRCLIB")

    if not DB2_SRCLIB:
        missing.append("DB2_SRCLIB")

    if not COPYLIB:
        missing.append("COPYLIB")

    if not LOADLIB:
        missing.append("LOADLIB")

    if not OBJLIB:
        missing.append("OBJLIB")

    if missing:
        raise PyZBuildError("Missing required .env values : " + ", ".join(missing))

#-----------------------*
#    Basic Validation   *
#-----------------------*

    try:
        int(PORT_RAW)

    except ValueError as exc:
        raise PyZBuildError("ZOSMF_PORT must be a valid integer.") from exc

    if not ACCEPTABLE_RCS:
        raise PyZBuildError("ACCEPTABLE_RC cannot be empty.")

    if len(ZOSUSER) < 2:
        raise PyZBuildError("ZOSMF_USERNAME must contain at least two characters.")

#-------------------------------*
#    Deining URL for REST API   *
#-------------------------------*

def base_url() -> str:
    return (f"https://{HOST}:{int(PORT_RAW)}")

def zosmf_url() -> str:
    return (f"{base_url()}""/zosmf")

def info_url() -> str:
    return (f"{zosmf_url()}""/info")

def jobs_url() -> str:
    return (f"{zosmf_url()}""/restjobs/jobs")

def dataset_member_url(dataset: str, member: str) -> str:

    return (f"{zosmf_url()}""/restfiles/ds/"f"{dataset}({member})")

#-----------------------*
#    Deining HEADERS    *
#-----------------------*

def api_headers(content_type: str) -> dict[str, str]:

    return { "Content-Type"        : content_type,
             "X-CSRF-ZOSMF-HEADER" : "*"
            }

#-------------------------*
#    Safe Response Body   *
#-------------------------*

def response_body(response: requests.Response) -> str:

    body = response.text.strip()

    if not body:
        return "<empty response>"
    
    if len(body) > 1000:
        return (body[:1000]+ "...")

    return body

#---------------------*
#   Response Check    *
#---------------------*

def check_response(response  : requests.Response, 
                   operation : str) -> None:

  #  ══════ HTTP 200 = Success ══════ #
    if 200 <= response.status_code < 300: return

    body = response_body(response)

 #  ══════ HTTP 401 = Invalid Username or Password ══════ #
    if response.status_code == 401:

        raise PyZBuildError(
            f"{operation} failed.\n"
            "HTTP Status : 401\n"
            f"Response    : {body}\n"
            "Error       : z/OSMF request rejected, due to invalid login credentials.\n"
            "Fix         : Check username and password.\n")

 #  ══════ HTTP 403 - Permission failure ══════ #
    if response.status_code == 403:

        raise PyZBuildError(
            f"{operation} failed.\n"
            "HTTP Status : 403\n"
            f"Response    : {body}\n"
             "Error      : Authentication succeeded, but the user may not have sufficient authority.\n"
             "Fix        : Try with UserID have sufficient authority.\n")

#  ══════ HTTP 404 - Not Found ══════ #
    if response.status_code == 404:

        raise PyZBuildError(
            f"{operation} failed.\n"
            "HTTP Status : 404\n"
            f"Response    : {body}\n"
            "Error       : The requested z/OSMF resource or data set/member could not be found.\n"
            "Fix         : Kindly Check z/OSMF resource or data set/member.\n")

#  ══════ Unexpected error ══════ #

    raise PyZBuildError(
        f"{operation} failed.\n"
        f"HTTP Status : "
        f"{response.status_code}\n"
        f"Response    : {body}"
    )

#-----------------------------*
#   z/OSMF Connection Test    *
#-----------------------------*

def test_zosmf_connection() -> None:

    print("Testing z/OSMF authentication...")

    try:
        response = session.get(info_url(),
                               headers = api_headers("application/json"),
                               timeout = REQUEST_TIMEOUT)
        
    except requests.RequestException as exc:
        raise PyZBuildError("❌️ Unable to connect to z/OSMF. ❌️ \n" 
                           f"Details: {exc}") from exc

 #  ══════ HTTP 200 = Success ══════ #
    if response.status_code == 200:

        print("    ✅ z/OSMF authentication successful")

        # Useful diagnostic.
        # Do NOT print cookie values.
        
        if "LtpaToken2" in session.cookies:
            print("    ✅ z/OSMF session cookie received")
        return

 #  ══════ HTTP 401 = Invalid Username or Password ══════ #
    if response.status_code == 401:
        
        raise PyZBuildError(
            "z/OSMF authentication failed.\n"
            "HTTP Status : 401\n"
            "\n"
            "Check:\n"
            "  - ZOSMF_HOST\n"
            "  - ZOSMF_PORT\n"
            "  - ZOSMF_USERNAME\n"
            "  - ZOSMF_PASSWORD"
        )

    check_response(
        response,
        "z/OSMF connection test"
    )


# ============================================================
# PROGRAM NAME
# ============================================================

def normalize_program_name(
    value: str
) -> str:

    name = Path(
        value
    ).name

    if name.lower().endswith(
        ".cbl"
    ):

        name = name[:-4]

    name = name.upper()

    if not re.fullmatch(
        r"[A-Z0-9@$#]{1,8}",
        name
    ):

        raise PyZBuildError(
            f"Invalid program/member name "
            f"'{name}'.\n"
            "PDS member names must be "
            "1-8 characters."
        )

    return name


# ============================================================
# LOCATE SOURCE
# ============================================================

def locate_source(
    source_argument: str
) -> tuple[Path, str]:

    candidate = Path(
        source_argument
    )

    if candidate.is_file():

        source_path = candidate

    else:

        candidate_with_extension = (
            Path(
                f"{source_argument}.cbl"
            )
        )

        if candidate_with_extension.is_file():

            source_path = (
                candidate_with_extension
            )

        else:

            raise PyZBuildError(
                "COBOL source file not found: "
                f"{source_argument}"
            )

    member_name = (
        normalize_program_name(
            source_path.stem
        )
    )

    return (
        source_path,
        member_name
    )


# ============================================================
# UPLOAD DATASET MEMBER
# ============================================================

def upload_dataset_member(
    dataset: str,
    member: str,
    content: str,
    description: str
) -> None:

    url = dataset_member_url(
        dataset,
        member
    )

    print(
        f"    Uploading to "
        f"{dataset}({member})..."
    )

    try:

        response = session.put(

            url,

            headers=api_headers(
                "text/plain"
            ),

            data=content.encode(
                "utf-8"
            ),

            timeout=REQUEST_TIMEOUT
        )

    except requests.RequestException as exc:

        raise PyZBuildError(
            f"{description} failed.\n"
            f"Network error: {exc}"
        ) from exc

    check_response(
        response,
        description
    )


# ============================================================
# DETECT COBOL PROGRAM TYPE
# ============================================================

def contains_exec_block(
    source_text: str,
    keyword: str
) -> bool:

    pattern = re.compile(
        rf"\bEXEC\s+{re.escape(keyword)}\b.*?\bEND-EXEC\b",
        re.IGNORECASE | re.DOTALL
    )

    return bool(
        pattern.search(source_text)
    )


def detect_program_type(
    source_text: str
) -> str:

    has_cics = contains_exec_block(
        source_text,
        "CICS"
    )

    has_db2 = contains_exec_block(
        source_text,
        "SQL"
    )

    if has_cics and has_db2:
        raise PyZBuildError(
            "Both EXEC CICS and EXEC SQL were detected. "
            "A combined CICS+DB2 JCL is required."
        )

    if has_cics:
        return "CICS-COB"

    if has_db2:
        return "DB2-COB"

    return "COBOL"


# ============================================================
# GENERATE COMPILE JCL
# ============================================================

def generate_compile_jcl(
    program_name: str
) -> tuple[str, str]:

    # --------------------------------------------------------
    # Generate JCL member name dynamically
    #
    # Example:
    # TREX007 -> COMPP07
    # --------------------------------------------------------

    jcl_member_name = f"COMPP{ZOSUSER[-2:]}"

    # --------------------------------------------------------
    # Dynamic Compile + Link JCL
    # --------------------------------------------------------

    generated_jcl = f"""//{jcl_member_name} JOB MAT,MAT,MSGLEVEL=(1,1),
//         CLASS=A,MSGCLASS=A,NOTIFY=&SYSUID,TIME=1440,REGION=0M
//**********************************************************************
//*               D E S C R I P T I O N                                *
//*               ---------------------                                *
//*        JCL TO COMPILE THE COBOL BATCH PROGRAMS.                    *
//*                                                                    *
//**********************************************************************
// SET PGM={program_name}
//*
//COMP$10  EXEC PGM=IGYCRCTL,REGION=640K,COND=(12,LE),
//         PARM=(NOTERM,OFFSET,DYNAM,XREF)
//*------------------------------------------------------------------*
//*                                                                  *
//*            COMPILE THE COBOL PROGRAM                             *
//*                                                                  *
//*------------------------------------------------------------------*
//*STEPLIB  DD  DSN=IGY.V6R4M0.SIGYCOMP,DISP=SHR
//SYSPRINT DD  SYSOUT=(A)
//SYSIN    DD  DISP=SHR,DSN=&SYSUID..P.COBOL.SRCLIB(&PGM)
//SYSPUNCH DD  DUMMY
//SYSUT1   DD  UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT2   DD  UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT3   DD  UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT4   DD  UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT5   DD  UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT6   DD  UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT7   DD  UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT8   DD  UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT9   DD  UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT10  DD  UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT11  DD  UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT12  DD  UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT13  DD  UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT14  DD  UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT15  DD  UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT16  DD  UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT17  DD  UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSLIB   DD  DSN=SYS1.MACLIB,DISP=SHR
//         DD  DSN=&SYSUID..P.CPYLIB,DISP=SHR
//SYSMDECK DD  DUMMY
//SYSLIN   DD  DSN=&SYSUID..P.OBJLIB(&PGM),DISP=SHR
//*
// IF COMP$10.RC LE 0004 THEN
//*
//LINK$20  EXEC  PGM=IEWL,REGION=2048K,COND=(12,LE)
//**********************************************************************
//*                                                                    *
//*         LINK EDIT THE COBOL PROGRAM                                *
//*                                                                    *
//**********************************************************************
//SYSPRINT DD  SYSOUT=(A)
//SYSLIN   DD  DSN=&SYSUID..P.OBJLIB(&PGM),DISP=SHR
//SYSLIB   DD  DSN=CEE.SCEELKED,DISP=SHR
//         DD  DSN=&SYSUID..P.COBOL.SRCLIB,DISP=SHR
//SYSLMOD  DD  DSN=&SYSUID..P.LOADLIB(&PGM),
//             DISP=SHR,DCB=(BLKSIZE=3072)
//SYSUT1   DD  UNIT=SYSDA,SPACE=(CYL,(2,2)),DISP=NEW
//*
// ENDIF
"""

    return (
        generated_jcl,
        jcl_member_name
    )


# ============================================================
# GENERATE CICS-COBOL COMPILE JCL
# ============================================================

def generate_cics_compile_jcl(
    program_name: str
) -> tuple[str, str]:

    jcl_member_name = "@CICSCOB"

    generated_jcl = f"""//@CICSCOB JOB ,'CICS-COBOL-COMPILER',MSGLEVEL=(1,1),
//         CLASS=A,MSGCLASS=A,NOTIFY=&SYSUID,TIME=1440,REGION=0M
//**********************************************************************
//*               D E S C R I P T I O N                                *
//*               ---------------------                                *
//*        JCL TO COMPILE THE CICS-COBOL ONLINE PROGRAMS.              *
//**********************************************************************
// SET MEMBER={program_name}
//*
//STEP#010 EXEC PGM=DFHECP1$,PARM='COBOL3',REGION=0M
//*
//STEPLIB  DD DISP=SHR,DSN=CICSTS61.CICS.SDFHLOAD
//*
//SYSIN    DD DSN={CICS_SRCLIB}(&MEMBER),DISP=SHR
//SYSPRINT DD SYSOUT=*
//*
//SYSPUNCH DD DSN=&&SYSCIN,
//            DISP=(,PASS),UNIT=SYSALLDA,
//            DCB=BLKSIZE=400,
//            SPACE=(400,(400,100))
//*
//STEP#020 EXEC PGM=IGYCRCTL,REGION=0M,
//   PARM='NODYNAM,LIB,OBJECT,RENT,APOST,MAP,XREF,NOSEQUENCE,OFFSET'
//*
//*STEPLIB  DD DSN=IGY.V6R4M0.SIGYCOMP,DISP=SHR
//*
//SYSLIB   DD DSN=&SYSUID..P.CPYLIB,DISP=SHR
//         DD DSN=CICSTS61.CICS.SDFHCOB,DISP=SHR
//         DD DSN=CICSTS61.CICS.SDFHMAC,DISP=SHR
//         DD DSN=CICSTS61.CICS.SDFHSAMP,DISP=SHR
//*
//SYSPRINT DD SYSOUT=*
//SYSMDECK DD DUMMY
//*
//SYSIN    DD DSN=&&SYSCIN,DISP=(OLD,DELETE)
//SYSLIN   DD DSN=&&LOADSET,DISP=(MOD,PASS),
//            UNIT=SYSALLDA,SPACE=(80,(250,100))
//SYSUT1   DD UNIT=SYSALLDA,SPACE=(460,(350,100))
//SYSUT2   DD UNIT=SYSALLDA,SPACE=(460,(350,100))
//SYSUT3   DD UNIT=SYSALLDA,SPACE=(460,(350,100))
//SYSUT4   DD UNIT=SYSALLDA,SPACE=(460,(350,100))
//SYSUT5   DD UNIT=SYSALLDA,SPACE=(460,(350,100))
//SYSUT6   DD UNIT=SYSALLDA,SPACE=(460,(350,100))
//SYSUT7   DD UNIT=SYSALLDA,SPACE=(460,(350,100))
//SYSUT8   DD UNIT=SYSALLDA,SPACE=(CYL,(2,2))
//SYSUT9   DD UNIT=SYSALLDA,SPACE=(CYL,(2,2))
//SYSUT10  DD UNIT=SYSALLDA,SPACE=(CYL,(2,2))
//SYSUT11  DD UNIT=SYSALLDA,SPACE=(CYL,(2,2))
//SYSUT12  DD UNIT=SYSALLDA,SPACE=(CYL,(2,2))
//SYSUT13  DD UNIT=SYSALLDA,SPACE=(CYL,(2,2))
//SYSUT14  DD UNIT=SYSALLDA,SPACE=(CYL,(2,2))
//SYSUT15  DD UNIT=SYSALLDA,SPACE=(CYL,(2,2))
//SYSUT16  DD UNIT=SYSALLDA,SPACE=(CYL,(2,2))
//SYSUT17  DD UNIT=SYSALLDA,SPACE=(CYL,(2,2))
//*
//STEP#030 EXEC PGM=IEBGENER,COND=(7,LT,STEP#020)
//SYSUT1   DD DSN=CICSTS61.CICS.SDFHSAMP(DFHEILID),DISP=SHR
//SYSUT2   DD DSN=&&COPYLINK,DISP=(NEW,PASS),
//            DCB=(LRECL=80,BLKSIZE=400,RECFM=FB),
//            UNIT=SYSALLDA,SPACE=(400,(20,20))
//SYSPRINT DD SYSOUT=*
//SYSIN    DD DUMMY
//*
//STEP#040 EXEC PGM=IEWL,REGION=4M,
//            PARM='LIST,XREF',COND=(5,LT,STEP#020)
//SYSLIB   DD DSN=CICSTS61.CICS.SDFHLOAD,DISP=SHR
//         DD DSN=CEE.SCEELKED,DISP=SHR
//SYSLMOD  DD DSN=COMMON.CICS.LOADLIB,DISP=SHR
//SYSUT1   DD UNIT=SYSALLDA,DCB=BLKSIZE=1024,
//            SPACE=(1024,(200,20))
//SYSPRINT DD SYSOUT=*
//SYSLIN   DD DSN=&&COPYLINK,DISP=(OLD,DELETE)
//         DD DSN=&&LOADSET,DISP=(OLD,DELETE)
//         DD DDNAME=SYSIN
//SYSIN DD *
    NAME {program_name}(R)
/*
//
//********************************************************************
//* STEP 6: CICS NEW COPY COMMAND
//********************************************************************
//NEWCOPY  EXEC PGM=IKJEFT01,REGION=4M
//STEPLIB  DD DSN=CICSTS61.CICS.SDFHLOAD,DISP=SHR
//SYSTSPRT DD SYSOUT=*
//SYSPRINT DD SYSOUT=*
//SYSTSIN  DD *
//    CEMT SET PROGRAM({program_name}) NEW
/*
"""

    return (
        generated_jcl,
        jcl_member_name
    )


# ============================================================
# GENERATE DB2-COBOL COMPILE JCL
# ============================================================

def generate_db2_compile_jcl(
    program_name: str
) -> tuple[str, str]:

    jcl_member_name = "#COBDBPC"

    generated_jcl = f"""//#COBDBPC JOB MAT,MAT,MSGLEVEL=(1,1),REGION=0M,
//       CLASS=E,MSGCLASS=A
//**********************************************************
//* DB2-COBOL PRECOMPILE, COMPILE, LINK AND BIND
//**********************************************************
// EXPORT SYMLIST=*
// SET COPYLIB=&SYSUID..COPYLIB
// SET DBRMLIB=&SYSUID..DBRMLIB
// SET LOADLIB=&SYSUID..LOADLIB
// SET SRCPDS={DB2_SRCLIB}
// SET MEM={program_name}
// SET PGM={program_name}
// SET LMOD={program_name}
// SET WSPC=500
// SET LIBPRFX='CEE'
//********************************************************************
//*        PRECOMPILE THE IBM COBOL PROGRAM
//********************************************************************
//PC       EXEC PGM=DSNHPC,
//         PARM='HOST(IBMCOB),SOURCE'
//DBRMLIB  DD DSN=&DBRMLIB(&MEM),DISP=SHR
//STEPLIB  DD DISP=SHR,DSN=DBD1.SDSNEXIT
//         DD DISP=SHR,DSN=DB2V13.SDSNLOAD
//         DD DISP=SHR,DSN=DB2V13.NEW.SDSNSAMP
//         DD DISP=SHR,DSN=DB2V13.SDSNSAMP
//         DD DISP=SHR,DSN=DB2V13.ADSNLOAD
//SYSLIB   DD DSN=&COPYLIB,DISP=SHR
//SYSCIN   DD DSN=&&DSNHOUT,DISP=(MOD,PASS),UNIT=SYSDA,
//            SPACE=(800,(&WSPC,&WSPC))
//SYSPRINT DD SYSOUT=*
//SYSTERM  DD SYSOUT=*
//SYSUT1   DD SPACE=(800,(&WSPC,&WSPC),,,ROUND)
//SYSUT2   DD SPACE=(800,(&WSPC,&WSPC),,,ROUND)
//SYSIN    DD DSN=&SRCPDS(&PGM),DISP=SHR
//********************************************************************
//*        COMPILE THE IBM COBOL PROGRAM IF PRECOMPILE RC <= 4
//********************************************************************
//COMPILE EXEC PGM=IGYCRCTL,REGION=640K,COND=(12,LE),
// PARM=('APOST',NOTERM,OFFSET,DYNAM,XREF)
//*STEPLIB DD DSN=IGY.V6R4M0.SIGYCOMP,DISP=SHR
//SYSPRINT DD SYSOUT=(A)
//SYSIN    DD DSN=&&DSNHOUT,DISP=(OLD,DELETE)
//SYSPUNCH DD DUMMY
//SYSUT1   DD UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT2   DD UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT3   DD UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT4   DD UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT5   DD UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT6   DD UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT7   DD UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT8   DD UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT9   DD UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT10  DD UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT11  DD UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT12  DD UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT13  DD UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT14  DD UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT15  DD UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT16  DD UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSUT17  DD UNIT=SYSDA,SPACE=(CYL,(2,2))
//SYSLIB   DD DSN=SYS1.MACLIB,DISP=SHR
//         DD DSN=&COPYLIB,DISP=SHR
//SYSMDECK DD DUMMY
//SYSLIN   DD DSN=&SYSUID..OBJLIB(&PGM),DISP=SHR
//***************************************************
//* STEP TO PRODUCE LOAD MODULE FROM OBJECT MODULE
//***************************************************
// IF COMPILE.RC LE 0004 THEN
//LINK   EXEC PGM=IEWL,REGION=2048K
//SYSPRINT DD SYSOUT=(A)
//SYSLIN   DD DSN=&SYSUID..OBJLIB(&PGM),DISP=SHR
//SYSLIB   DD DSN=CEE.SCEELKED,DISP=SHR
//         DD DSN=&SYSUID..SRCLIB,DISP=SHR
//SYSLMOD  DD DSN=&LOADLIB(&PGM),
//             DISP=SHR,DCB=(BLKSIZE=3072)
//SYSUT1   DD UNIT=SYSDA,SPACE=(CYL,(2,2)),DISP=NEW
// ENDIF
//BINDPKG  EXEC PGM=IKJEFT01
//STEPLIB  DD DISP=SHR,DSN=DBD1.SDSNEXIT
//         DD DISP=SHR,DSN=&SYSUID..LOADLIB
//         DD DISP=SHR,DSN=DB2V13.SDSNLOAD
//DBRMLIB  DD DSN=&SYSUID..DBRMLIB,DISP=SHR
//SYSPRINT DD SYSOUT=*
//SYSTSPRT DD SYSOUT=*
//SYSTSIN  DD *,SYMBOLS=JCLONLY
  DSN SYSTEM (DBD1)
  BIND PACKAGE (DBD1LOC) -
       MEMBER (&MEM) -
       ACTION (REP) -
       ISOLATION (CS) -
       VALIDATE (BIND) -
       RELEASE (COMMIT) -
       OWNER (&SYSUID) -
       QUALIFIER (IBMUSER) -
       ENCODING (1047)
  END
/*
//BINDPLN  EXEC PGM=IKJEFT01
//STEPLIB  DD DISP=SHR,DSN=DBD1.SDSNEXIT
//         DD DISP=SHR,DSN=&SYSUID..LOADLIB
//         DD DISP=SHR,DSN=DB2V13.SDSNLOAD
//DBRMLIB  DD DSN=&SYSUID..DBRMLIB,DISP=SHR
//SYSPRINT DD SYSOUT=*
//SYSTSPRT DD SYSOUT=*
//SYSTSIN  DD *,SYMBOLS=JCLONLY
  DSN SYSTEM (DBD1)
  BIND PKLIST (DBD1LOC.&MEM) -
       PLAN (&MEM) -
       ACTION (REP) -
       ISOLATION (CS) -
       VALIDATE (BIND) -
       RELEASE (COMMIT) -
       OWNER (&SYSUID) -
       QUALIFIER (IBMUSER) -
       ENCODING (1047)
  END
/*
"""

    return (
        generated_jcl,
        jcl_member_name
    )



# ============================================================
# SUBMIT JCL
# ============================================================

def submit_jcl_member(
    jcl_dataset: str,
    jcl_member: str
) -> dict[str, Any]:

    payload = {

        "file":
            f"//'{jcl_dataset}"
            f"({jcl_member})'"
    }

    print(
        f"    Submitting "
        f"{jcl_dataset}"
        f"({jcl_member})..."
    )

    try:

        response = session.put(

            jobs_url(),

            headers=api_headers(
                "application/json"
            ),

            json=payload,

            timeout=REQUEST_TIMEOUT
        )

    except requests.RequestException as exc:

        raise PyZBuildError(
            "Job submission network error:\n"
            f"{exc}"
        ) from exc

    check_response(
        response,
        "Job submission"
    )

    try:

        data = response.json()

    except ValueError as exc:

        raise PyZBuildError(
            "z/OSMF returned invalid JSON "
            "after job submission."
        ) from exc

    for field in (
        "jobname",
        "jobid"
    ):

        if not data.get(field):

            raise PyZBuildError(
                "z/OSMF job response did not "
                f"contain '{field}'.\n"
                f"Response: {data}"
            )

    return data


# ============================================================
# GET JOB
# ============================================================

def get_job(
    job_name: str,
    job_id: str
) -> dict[str, Any]:

    url = (
        f"{jobs_url()}/"
        f"{job_name}/"
        f"{job_id}"
    )

    try:

        response = session.get(

            url,

            headers=api_headers(
                "application/json"
            ),

            timeout=REQUEST_TIMEOUT
        )

    except requests.RequestException as exc:

        raise PyZBuildError(
            f"Unable to query job "
            f"{job_name}/{job_id}.\n"
            f"Network error: {exc}"
        ) from exc

    check_response(
        response,
        f"Get job {job_name}/{job_id}"
    )

    try:

        return response.json()

    except ValueError as exc:

        raise PyZBuildError(
            f"Invalid JSON returned for "
            f"job {job_name}/{job_id}."
        ) from exc


# ============================================================
# MONITOR JOB
# ============================================================

def wait_for_job(
    job_name: str,
    job_id: str,
    timeout_seconds: int,
    poll_interval: int
) -> dict[str, Any]:

    start_time = time.monotonic()

    while True:

        elapsed = (
            time.monotonic()
            - start_time
        )

        if elapsed >= timeout_seconds:

            raise PyZBuildError(
                f"Job {job_name}/{job_id} "
                f"timed out after "
                f"{timeout_seconds} seconds."
            )

        job_data = get_job(
            job_name,
            job_id
        )

        status = job_data.get(
            "status"
        )

        retcode = job_data.get(
            "retcode"
        )

        print(
            f"\rJob "
            f"{job_name}/{job_id} | "
            f"Status: "
            f"{status or '-':<10} | "
            f"RC: "
            f"{retcode or '-':<15}",
            end="",
            flush=True
        )

        if retcode is not None:

            print()

            return job_data

        time.sleep(
            poll_interval
        )


# ============================================================
# PARSE RETURN CODE
# ============================================================

def parse_cc(
    retcode: Any
) -> int | None:

    if retcode is None:

        return None

    text = (
        str(retcode)
        .strip()
        .upper()
    )

    match = re.search(
        r"\bCC\s*0*(\d+)\b",
        text
    )

    if not match:

        return None

    return int(
        match.group(1)
    )


# ============================================================
# BUILD RESULT
# ============================================================

def build_result(
    retcode: Any
) -> tuple[str, int]:

    cc = parse_cc(
        retcode
    )

    if cc is None:

        return (
            "FAILURE",
            1
        )

    if cc == 0:

        return (
            "SUCCESS",
            0
        )

    if (
        cc == 4
        and 4 in ACCEPTABLE_RCS
    ):

        return (
            "SUCCESS_WITH_WARNINGS",
            0
        )

    if cc in ACCEPTABLE_RCS:

        return (
            "SUCCESS_WITH_WARNINGS",
            0
        )

    return (
        "FAILURE",
        max(cc, 1)
    )


# ============================================================
# DISPLAY BANNER
# ============================================================

def print_banner() -> None:

    print()

    print(
        "========== 🚀 PyZBuild v0.1 =========="
    )

    print(
        "HOST         :",
        "*******"
        if HOST
        else "<not set>"
    )

    print(
        "PORT         :",
        PORT_RAW
        or "<not set>"
    )

    print(
        "ZOSUSER      :",
        ZOSUSER
        or "<not set>"
    )

    print(
        "PASSWORD     :",
        "*******"
        if PASSWORD
        else "<not set>"
    )

    print(
        "VERIFY_SSL   :",
        VERIFY_SSL
    )

    print(
        "ACCEPTABLE_RC:",
        sorted(
            ACCEPTABLE_RCS
        )
    )

    print(
        "SRCLIB       :",
        SRCLIB
    )

    print(
        "CICS_SRCLIB  :",
        CICS_SRCLIB
    )

    print(
        "DB2_SRCLIB   :",
        DB2_SRCLIB
    )

    print(
        "======================================"
    )

    print()


# ============================================================
# MAIN BUILD
# ============================================================

def run_single_build(
    program_argument: str
) -> int:

    # --------------------------------------------------------
    # Configuration
    # --------------------------------------------------------

    validate_environment()

    configure_session()

    print_banner()

    # --------------------------------------------------------
    # Authentication
    # --------------------------------------------------------

    test_zosmf_connection()

    print()

    # --------------------------------------------------------
    # Locate source
    # --------------------------------------------------------

    (
        source_path,
        member_name
    ) = locate_source(
        program_argument
    )

    print(
        "Program :",
        member_name
    )

    print(
        "Source  :",
        source_path
    )

    print(
        "SRCLIB  :",
        SRCLIB
    )

    print(
        "JCLLIB  :",
        JCLLIB
    )

    print()

    # ========================================================
    # 1/5 Upload COBOL
    # ========================================================

    print(
        "1/5 Reading COBOL source..."
    )

    source_text = (
        source_path.read_text(
            encoding="utf-8"
        )
    )

    program_type = detect_program_type(
        source_text
    )

    if program_type == "CICS-COB":

        source_library = CICS_SRCLIB

        print(
            "    Program type : CICS-COB"
        )

        print(
            "    Detected    : EXEC CICS ... END-EXEC"
        )

        generated_jcl, jcl_member = (
            generate_cics_compile_jcl(
                member_name
            )
        )

    elif program_type == "DB2-COB":

        source_library = DB2_SRCLIB

        print(
            "    Program type : DB2-COB"
        )

        print(
            "    Detected    : EXEC SQL ... END-EXEC"
        )

        generated_jcl, jcl_member = (
            generate_db2_compile_jcl(
                member_name
            )
        )

    else:

        source_library = SRCLIB

        print(
            "    Program type : COBOL"
        )

        print(
            "    Detected    : No EXEC CICS/SQL block"
        )

        generated_jcl, jcl_member = (
            generate_compile_jcl(
                member_name
            )
        )

    print(
        "    Source library :",
        source_library
    )

    print(
        "    JCL member     :",
        jcl_member
    )

    print()

    upload_dataset_member(

        source_library,

        member_name,

        source_text,

        (
            f"Upload "
            f"{source_path.name} "
            f"to "
            f"{source_library}"
            f"({member_name})"
        )
    )

    print(
        "    ✅ COBOL source uploaded"
    )

    # ========================================================
    # 2/5 Generate and upload JCL
    # ========================================================

    print(
        "2/5 Generating build JCL..."
    )

    upload_dataset_member(

        JCLLIB,

        jcl_member,

        generated_jcl,

        (
            "Upload generated JCL "
            f"to "
            f"{JCLLIB}"
            f"({jcl_member})"
        )
    )

    print(
        f"    ✅ JCL uploaded as "
        f"{JCLLIB}"
        f"({jcl_member})"
    )

    # ========================================================
    # 3/5 Submit
    # ========================================================

    print(
        "3/5 Submitting build job..."
    )

    submission = (
        submit_jcl_member(

            JCLLIB,

            jcl_member
        )
    )

    job_name = submission[
        "jobname"
    ]

    job_id = submission[
        "jobid"
    ]

    owner = submission.get(
        "owner",
        ZOSUSER
    )

    print(
        "    ✅ Job submitted"
    )

    print(
        "       Job name :",
        job_name
    )

    print(
        "       Job ID   :",
        job_id
    )

    print(
        "       Owner    :",
        owner
    )

    # ========================================================
    # 4/5 Monitor
    # ========================================================

    print(
        "4/5 Monitoring build..."
    )

    final_job = wait_for_job(

        job_name=job_name,

        job_id=job_id,

        timeout_seconds=BUILD_TIMEOUT,

        poll_interval=POLL_INTERVAL
    )

    # ========================================================
    # 5/5 Result
    # ========================================================

    retcode = final_job.get(
        "retcode"
    )

    status = final_job.get(
        "status"
    )

    result, exit_code = (
        build_result(
            retcode
        )
    )

    print()

    print(
        "5/5 Build result"
    )

    print(
        "=" * 50
    )

    print(
        "Program :",
        member_name
    )

    print(
        "Jobname :",
        job_name
    )

    print(
        "JobID   :",
        job_id
    )

    print(
        "Owner   :",
        owner
    )

    print(
        "Status  :",
        status
    )

    print(
        "MAXCC   :",
        retcode
    )

    print(
        "Result  :",
        result
    )

    print(
        "=" * 50
    )

    return exit_code


def normalize_program_arguments(
    values: list[str]
) -> list[str]:

    programs: list[str] = []

    for value in values:

        for program in value.split(","):

            program = program.strip()

            if program:
                programs.append(program)

    if not programs:
        raise PyZBuildError(
            "No COBOL programs were provided."
        )

    return programs


def run_build(
    program_arguments: list[str]
) -> int:

    # --------------------------------------------------------
    # Configuration
    # --------------------------------------------------------

    validate_environment()

    configure_session()

    print_banner()

    # --------------------------------------------------------
    # Authentication
    # --------------------------------------------------------

    test_zosmf_connection()

    print()

    # --------------------------------------------------------
    # Normalize program list
    # --------------------------------------------------------

    programs = normalize_program_arguments(
        program_arguments
    )

    print(
        f"Programs requested : {len(programs)}"
    )

    for program in programs:
        print(
            f"    - {program}"
        )

    print()

    # --------------------------------------------------------
    # Build each program
    # --------------------------------------------------------

    failed_programs: list[str] = []

    successful_programs: list[str] = []

    for index, program in enumerate(
        programs,
        start=1
    ):

        print()
        print("=" * 70)

        print(
            f"BUILD {index}/{len(programs)} : "
            f"{program}"
        )

        print("=" * 70)

        try:

            exit_code = run_single_build(
                program
            )

            if exit_code == 0:

                successful_programs.append(
                    program
                )

            else:

                failed_programs.append(
                    program
                )

        except PyZBuildError as exc:

            failed_programs.append(
                program
            )

            print(
                f"\n❌ {program} failed."
            )

            print(
                f"   {exc}"
            )

    # --------------------------------------------------------
    # Final summary
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print(
        "                 PyZBuild SUMMARY"
    )
    print("=" * 70)

    print(
        f"Total programs : {len(programs)}"
    )

    print(
        f"Successful     : "
        f"{len(successful_programs)}"
    )

    print(
        f"Failed         : "
        f"{len(failed_programs)}"
    )

    if successful_programs:

        print()
        print(
            "Successful programs:"
        )

        for program in successful_programs:

            print(
                f"    ✅ {program}"
            )

    if failed_programs:

        print()
        print(
            "Failed programs:"
        )

        for program in failed_programs:

            print(
                f"    ❌ {program}"
            )

    print("=" * 70)

    if failed_programs:

        return 1

    return 0


# ============================================================
# CLI
# ============================================================

def parse_arguments() -> argparse.Namespace:

    parser = argparse.ArgumentParser(

        description=(
            "PyZBuild - "
            "z/OS COBOL build automation"
        )
    )

    subparsers = (
        parser.add_subparsers(
            dest="command",
            required=True
        )
    )

    build_parser = (
        subparsers.add_parser(
            "build",
            help="Build a COBOL program"
        )
    )

    build_parser.add_argument(

        "programs",

        nargs="+",

        help=(
            "One or more COBOL source files or "
            "program names. "
            "Examples: TEST TEST2.cbl "
            "or TEST,TEST2"
        )
    )

    return parser.parse_args()


# ============================================================
# ENTRY POINT
# ============================================================

def main() -> int:

    args = parse_arguments()

    try:

        if args.command == "build":

            return run_build(
                args.programs
            )

        raise PyZBuildError(
            f"Unsupported command: "
            f"{args.command}"
        )

    except KeyboardInterrupt:

        print(
            "\n\nBuild cancelled."
        )

        return 130

    except PyZBuildError as exc:

        print(
            f"\n❌ PyZBuild ERROR:\n"
            f"{exc}",
            file=sys.stderr
        )

        return 1

    except requests.RequestException as exc:

        print(
            f"\n❌ Network/API ERROR:\n"
            f"{exc}",
            file=sys.stderr
        )

        return 2

    except OSError as exc:

        print(
            f"\n❌ File/System ERROR:\n"
            f"{exc}",
            file=sys.stderr
        )

        return 3

    except ValueError as exc:

        print(
            f"\n❌ Configuration ERROR:\n"
            f"{exc}",
            file=sys.stderr
        )

        return 4


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    retcode = main()

    if retcode == 0 or retcode == 4 :
        print(f"PyZBuild SUCCESS - MAXCC: {retcode}")
        sys.exit(0)

    else:
        print(f"PyZBuild FAILED - MAXCC: {retcode}")
        sys.exit(1)