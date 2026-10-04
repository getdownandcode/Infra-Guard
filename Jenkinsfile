pipeline {
    agent {
        dockerfile {
            filename 'Dockerfile.jenkins-agent'
            args '-u root -v /var/run/docker.sock:/var/run/docker.sock -e AWS_DEFAULT_REGION -e AWS_REGION -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN'
        }
    }

    parameters {
        booleanParam(name: 'CONFIRM_CLEANUP', defaultValue: false, description: 'Confirm actual deletion/mutation of eligible idle AWS resources')
        string(name: 'RESOURCE_TAG_KEY', defaultValue: '', description: 'Optional tag key to restrict cleanup')
        string(name: 'RESOURCE_TAG_VALUE', defaultValue: '', description: 'Optional tag value required with RESOURCE_TAG_KEY')
    }

    options {
        timeout(time: 10, unit: 'MINUTES')
        timestamps()
    }

    triggers {
        cron('H H * * 0')
    }

    environment {
        AWS_DEFAULT_REGION = "${env.AWS_DEFAULT_REGION ?: 'ap-south-1'}"
        S3_STATE_BUCKET = "${env.S3_STATE_BUCKET ?: ''}"
        MONITORING_DIR = 'monitoring'
    }

    stages {
        stage('Lint') {
            steps {
                sh 'python3 -m py_compile scripts/cleanup.py'
                sh 'python3 scripts/cleanup.py --help > /dev/null'
                sh 'bash -n scripts/bootstrap_s3.sh && bash -n scripts/s3-sync.sh'
            }
        }

        stage('Validate') {
            steps {
                sh 'aws sts get-caller-identity'
                sh 'bash scripts/bootstrap_s3.sh'
                sh 'python3 scripts/cleanup.py --dry-run ${S3_STATE_BUCKET ? "--log-bucket " + S3_STATE_BUCKET : ""}'
            }
        }

        stage('Apply') {
            when {
                anyOf {
                    triggeredBy 'TimerTrigger'
                    expression { params.CONFIRM_CLEANUP == true }
                }
            }
            steps {
                script {
                    def bucketArg = env.S3_STATE_BUCKET ? "--log-bucket ${env.S3_STATE_BUCKET}" : ""
                    def tagArgs = ""
                    if (params.RESOURCE_TAG_KEY) {
                        tagArgs += " --resource-tag-key ${params.RESOURCE_TAG_KEY}"
                        if (params.RESOURCE_TAG_VALUE) {
                            tagArgs += " --resource-tag-value ${params.RESOURCE_TAG_VALUE}"
                        }
                    }
                    sh "python3 scripts/cleanup.py --confirm ${bucketArg} ${tagArgs}"
                }
            }
        }

        stage('Sync-to-S3') {
            steps {
                sh 'bash scripts/s3-sync.sh'
            }
        }

        stage('Deploy Monitoring') {
            steps {
                dir("${MONITORING_DIR}") {
                    sh 'docker compose up -d'
                }
            }
        }
    }

    post {
        failure {
            echo 'Infra-Guard pipeline failed.'
        }
    }
}
