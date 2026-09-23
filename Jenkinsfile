pipeline {
    agent {
        dockerfile {
            filename 'Dockerfile.jenkins-agent'
            args '-u root -v /var/run/docker.sock:/var/run/docker.sock'
        }
    }

    options {
        timeout(time: 5, unit: 'MINUTES')
        timestamps()
    }

    triggers {
        cron('H H * * 0')
    }

    environment {
        AWS_DEFAULT_REGION = "${env.AWS_DEFAULT_REGION ?: 'ap-south-1'}"
        S3_STATE_BUCKET = "${env.S3_STATE_BUCKET ?: 'infra-guard-state'}"
        MONITORING_DIR = 'monitoring'
    }

    stages {
        stage('Lint') {
            steps {
                sh 'python3 -m py_compile scripts/cleanup.py'
                sh 'bash -n scripts/bootstrap_s3.sh && bash -n scripts/s3-sync.sh'
            }
        }

        stage('Validate') {
            steps {
                sh 'aws sts get-caller-identity'
                sh 'bash scripts/bootstrap_s3.sh'
                sh 'aws s3 ls s3://${S3_STATE_BUCKET} || echo "Bucket ${S3_STATE_BUCKET} not accessible or not created"'
                sh 'python3 scripts/cleanup.py --dry-run --log-bucket ${S3_STATE_BUCKET}'
            }
        }

        stage('Apply') {
            when {
                anyOf {
                    branch 'main'
                    triggeredBy 'TimerTrigger'
                }
            }
            steps {
                sh 'python3 scripts/cleanup.py --confirm --log-bucket ${S3_STATE_BUCKET}'
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
