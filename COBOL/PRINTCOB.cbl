000100 IDENTIFICATION DIVISION.                                         
000200 PROGRAM-ID. PRINTCOB.                                            
000300****************************************************************  
000400*              D E S C R I P T I O N                           *  
000500*              ---------------------                           *  
000600*                                                              *  
000700*       PRINTCOB - THIS PROGRAM READS THE INPUT FILE AND       *  
000800*                  PRINT IN THE SPOOL.                         * 
000900*                                                              *  
001000****************************************************************  
001100 ENVIRONMENT DIVISION.                                            
001200*                                                                 
001300 CONFIGURATION SECTION.                                           
001400 SOURCE-COMPUTER. IBM-PC.                                         
001500 OBJECT-COMPUTER. IBM-PC.                                         
001600*                                                                 
001700 INPUT-OUTPUT  SECTION.                                           
001800*                                                                 
001900 FILE-CONTROL.                                                    
002000      SELECT IN-FILE ASSIGN TO INPUTF                             
002100      ORGANIZATION IS SEQUENTIAL                                  
002200      ACCESS MODE IS SEQUENTIAL                                   
002300      FILE STATUS IS WS-INPUT-STS.                                
002400*                                                                 
002500 DATA DIVISION.                                                   
002600*                                                                 
002700 FILE SECTION.                                                    
002800*                                                                 
002900 FD IN-FILE.                                                      
003000*   
003100 01  INP-CARM-REC.                                               
003200*                                                                
003300     03 INP-KEY.                                                 
003400        05 INP-ACCT-NUMBER       PIC  X(19).                     
003500        05 FILLER                PIC  X(02).                     
003600        05 INP-PLAN              PIC  X(10).                     
003700*                                                                
003800     03 FILLER                   PIC  X(02).                     
003900     03 INP-CUST-NAME            PIC  X(13).                     
004000     03 FILLER                   PIC  X(02).                     
004100     03 INP-CR-LIMIT             PIC  X(13).                     
004200     03 FILLER                   PIC  X(19).                     
004300*                                                                
004400 WORKING-STORAGE SECTION.                                        
004500*                                                                
004600 01  WS-WORKING-VARIABLES.                                       
004700*                                                 
004710     03  WS-NEW-DUMMY-2          PIC  X(02)  VALUE SPACES. 
004720     03  WS-NEW-DUMMY-3          PIC  X(02)  VALUE SPACES.    
004730     03  WS-NEW-DUMMY-4          PIC  X(02)  VALUE SPACES.           
004800     03  WS-INPUT-STS            PIC  X(02)  VALUE SPACES.      
004900*                                                                
005000     03  WS-ABEND.                                               
005100         05 WS-RTNCODE           PIC  S9(9)  VALUE 9999.         
005200         05 WS-TIMING            PIC  S9(9)  VALUE ZEROS.        
005300*                                                                
005400     03  WS-EOF                  PIC  X(01)  VALUE 'N'.          
005500         88 WS-EOF-YES                       VALUE 'Y'.          
005600         88 WS-EOF-NO                        VALUE 'N'.          
005700*                                                                
005800*--------------------------*                                     
005900*     PROCEDURE DIVISION   *                                     
006000*--------------------------*                                     
006100 PROCEDURE DIVISION.                                             
006200*                                                             
006300 0000-MAIN-LINE-PARA.                                         
006400*                                                             
006500      PERFORM 1000-OPEN-PARA                                  
006600         THRU 1999-OP-EXIT                                    
006700*                                                             
006800      PERFORM 2000-PROCESS-PARA                               
006900         THRU 2999-PR-EXIT                                    
007000        UNTIL WS-EOF = 'Y'                                    
007100*                                                             
007200      PERFORM 8000-CLOSE-PARA                                 
007300         THRU 8999-CP-EXIT                                    
007400*                                                             
007500      STOP RUN.                                               
007600*                                                             
007700*9999-MAIN-LINE-EXIT.                                         
007800*                                                             
007900*----------------------*                                      
008000*     OPEN-PARA        *                                      
008100*----------------------*                                      
008200 1000-OPEN-PARA.                                              
008300*                                                             
008400     OPEN INPUT IN-FILE                                       
008500*                                                             
008600     IF  WS-INPUT-STS IS EQUAL TO ZEROS                       
008700         CONTINUE                                             
008800     ELSE                                                     
008900         DISPLAY 'OPEN-INPUT FAILED : ' WS-INPUT-STS          
009000         CALL "CEE3ABD" USING WS-RTNCODE, WS-TIMING           
009100         GOBACK                                               
009200     END-IF                                                   
009300*                                                 
009400     PERFORM 2100-READ-INPUT-PARA                 
009500        THRU 2199-RIP-EXIT.                       
009600*                                                 
009700 1999-OP-EXIT.                                    
009800     EXIT.                                        
009900*                                                 
010000*----------------------*                          
010100*     PROCESS-PARA     *                          
010200*----------------------*                          
010300 2000-PROCESS-PARA.                               
010400*                                                 
010500     PERFORM 2100-READ-INPUT-PARA                 
010600        THRU 2199-RIP-EXIT.                       
010700*                                                 
010800 2999-PR-EXIT.                                    
010900     EXIT.                                        
011000*                                                 
011100*----------------------*                          
011200*   READ-PARA          *                          
011300*----------------------*                          
011400 2100-READ-INPUT-PARA.                            
011500*                                                 
011600     READ IN-FILE                                 
011700          AT END                                  
011800                MOVE 'Y'         TO WS-EOF        
011900          NOT AT END                              
012000                DISPLAY INP-CARM-REC              
012100     END-READ.                                    
012200*                                                 
012300 2199-RIP-EXIT.                                   
012400     EXIT.                                                 
012500*                                                          
012600*----------------------*                                   
012700*   CLOSE-PARA         *                                   
012800*----------------------*                                   
012900 8000-CLOSE-PARA.                                          
013000*                                                          
013100     CLOSE IN-FILE                                         
013200*                                                          
013300     IF  WS-INPUT-STS IS EQUAL TO ZEROS                    
013400         CONTINUE                                          
013500     ELSE                                                  
013600         DISPLAY 'CLOSE-INPUT FAILED : ' WS-INPUT-STS      
013700         CALL "CEE3ABD" USING WS-RTNCODE, WS-TIMING        
013800         GOBACK                                            
013900     END-IF.                                             
014000*      
014100 8999-CP-EXIT.                                             
014200     EXIT.                                                 
