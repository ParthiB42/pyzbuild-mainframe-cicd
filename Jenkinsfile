pipeline {

    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
    }

    environment {
        PYTHON = "python"
        PYZBUILD = "src\\PyZBuild\\PyZBuild.py"
    }

    triggers {
        githubPush()
    }

    stages {

        stage('Checkout') {
            steps {
                echo "Checking out source code..."

                checkout([
                    $class: 'GitSCM',
                    branches: [[name: "${env.BRANCH_NAME ?: '*/main'}"]],
                    userRemoteConfigs: [[
                        url: 'https://github.com/ParthiB42/pyzbuild-mainframe-cicd.git',
                        credentialsId: 'GitHub_Jenkins'
                    ]]
                ])
            }
        }

        stage('Setup Python Environment') {
            steps {
                bat '''
                    echo Creating Python virtual environment...
                    %PYTHON% -m venv .venv

                    echo Installing dependencies...
                    .venv\\Scripts\\python.exe -m pip install --upgrade pip
                    .venv\\Scripts\\python.exe -m pip install -r requirements.txt
                '''
            }
        }

        stage('Detect Changed COBOL Programs') {
            steps {
                script {

                    def changedFiles = ""

                    if (env.GIT_PREVIOUS_SUCCESSFUL_COMMIT) {

                        echo "Comparing with previous successful build..."

                        changedFiles = bat(
                            returnStdout: true,
                            script: """
                                git diff --name-only ${env.GIT_PREVIOUS_SUCCESSFUL_COMMIT} ${env.GIT_COMMIT}
                            """
                        ).trim()

                    } else {

                        echo "First build - detecting files from current commit..."

                        changedFiles = bat(
                            returnStdout: true,
                            script: """
                                git diff-tree --no-commit-id --name-only -r ${env.GIT_COMMIT}
                            """
                        ).trim()
                    }

                    def programs = changedFiles
                        .readLines()
                        .findAll { file ->
                            file.toLowerCase().endsWith('.cbl')
                        }
                        .collect { file ->
                            def name = file.tokenize('/\\\\')[-1]
                            name.substring(0, name.lastIndexOf('.'))
                        }
                        .unique()

                    if (programs.isEmpty()) {

                        echo "No COBOL programs changed."
                        env.CHANGED_PROGRAMS = ""

                    } else {

                        env.CHANGED_PROGRAMS = programs.join(' ')

                        echo "Changed COBOL programs:"
                        programs.each { program ->
                            echo "  -> ${program}"
                        }
                    }
                }
            }
        }

        stage('Run PyZBuild') {
            when {
                expression {
                    return env.CHANGED_PROGRAMS?.trim()
                }
            }

            steps {

                echo "Starting PyZBuild..."

                /*
                 * z/OSMF credentials should be configured
                 * in Jenkins Credentials.
                 *
                 * Credential ID:
                 * ZOSMF_CREDENTIALS
                 */

                withCredentials([
                    usernamePassword(
                        credentialsId: 'ZOSMF_CREDENTIALS',
                        usernameVariable: 'ZOSMF_USER',
                        passwordVariable: 'ZOSMF_PASSWORD'
                    )
                ]) {

                    bat """
                        echo ==========================================
                        echo          PyZBuild Mainframe Build
                        echo ==========================================

                        echo Changed Programs:
                        echo %CHANGED_PROGRAMS%

                        .venv\\Scripts\\python.exe %PYZBUILD% build %CHANGED_PROGRAMS%
                    """
                }
            }
        }

        stage('Build Summary') {
            steps {

                script {

                    if (env.CHANGED_PROGRAMS?.trim()) {

                        echo "=========================================="
                        echo " PyZBuild CI/CD BUILD COMPLETED"
                        echo "=========================================="
                        echo "Programs Built : ${env.CHANGED_PROGRAMS}"
                        echo "Build Status   : SUCCESS"
                        echo "=========================================="

                    } else {

                        echo "No COBOL changes detected."
                        echo "Nothing to build."
                    }
                }
            }
        }
    }

    post {

        success {
            echo "PyZBuild Jenkins Pipeline: SUCCESS"
        }

        failure {
            echo "PyZBuild Jenkins Pipeline: FAILURE"
            echo "Check the console output and PyZBuild logs."
        }

        always {
            echo "PyZBuild pipeline execution completed."
        }
    }
}