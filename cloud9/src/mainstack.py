import os
from aws_cdk import (
    Duration,
    CfnTag,
    Stack,
    CustomResource,
    CfnParameter,
    CfnCondition,
    Fn,
    Aws,
    aws_cloud9 as cloud9,
    aws_ssm as ssm,
    aws_lambda as lambda_,
    aws_iam as iam,
)
from constructs import Construct

class MainStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        ee_team_role_arn = CfnParameter(self, 'EETeamRoleArn',
            default=''
        )

        CfnCondition(self, 'EeTeamRoleArnCondition', 
            expression=Fn.condition_equals(ee_team_role_arn.value_as_string, '')
        )

        owner_arn = Fn.condition_if('EeTeamRoleArnCondition', 
            Aws.NO_VALUE,
            'arn:aws:sts::{}:assumed-role/TeamRole/MasterKey'.format(Aws.ACCOUNT_ID)
        )

        c9 = cloud9.CfnEnvironmentEC2(self,'MyCfnEnvironmentEC2',
            instance_type='m4.large',
            automatic_stop_time_minutes=120,
            image_id='amazonlinux-2-x86_64',
            name='Workshop Cloud9',
            description='Workshop Cloud9',
            owner_arn=owner_arn.to_string(),
            tags=[CfnTag(key='SSMBootstrap', value='Active')]
        )

        with open(os.path.join(os.path.dirname(__file__), 'script.sh'), encoding='utf8') as fp:
            script = fp.read().splitlines()

        doc=ssm.CfnDocument(self, 'SsmDocBootstrapC9',
            name='BootstrapC9',
            document_type='Command',
            content={
                'schemaVersion': '2.2',
                'description': 'Bootstrap Cloud9',
                'mainSteps': [{
                    'name': 'BootstrapCloud9',
                    'action': 'aws:runShellScript',
                    'inputs': {
                        'runCommand': script
                    }
                }]
            }
        )

        association = ssm.CfnAssociation(self, 'SsmDocBootstrapC9Association',
            name=doc.ref,
            targets=[ssm.CfnAssociation.TargetProperty(
                key='tag:SSMBootstrap',
                values=['Active']
            )],
        )
        c9.node.add_dependency(association)

        lambda_role = iam.Role(self, 'LambdaRole',
            assumed_by =iam.ServicePrincipal('lambda.amazonaws.com'),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name('service-role/AWSLambdaBasicExecutionRole'),
                iam.ManagedPolicy.from_aws_managed_policy_name('AdministratorAccess')
            ]
        )

        with open(os.path.join(os.path.dirname(__file__), 'lambda.py'), encoding='utf8') as fp:
            handler_code = fp.read()

        on_event_fn = lambda_.Function(self, 'SetInstanceProfileLambda',
            code=lambda_.InlineCode(handler_code),
            handler='index.on_event',
            timeout=Duration.seconds(300),
            runtime=lambda_.Runtime.PYTHON_3_9,
            role=lambda_role
        )

        c9_role = iam.Role(self, 'C9Role',
            assumed_by =iam.ServicePrincipal('ec2.amazonaws.com'),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name('AdministratorAccess')
            ]
        )

        c9_instance_profile = iam.CfnInstanceProfile(self, 'C9InstanceProfile',
            roles=[c9_role.role_name]
        )
        
        CustomResource(self, 'SetInstanceProfileResource',
            service_token=on_event_fn.function_arn,
            properties={
                'InstanceProfileArn': c9_instance_profile.attr_arn,
                'InstanceProfileName': c9_instance_profile.ref
            }
        )

