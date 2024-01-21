import os
import pulumi
import pulumi_docker as docker
import pulumi_aws as aws
import pulumi_awsx as awsx
import pulumi_eks as eks
import pulumi_kubernetes as k8s

from pulumi import ComponentResource

# TODO: Encapsulate the below resources
class EKSCluster(ComponentResource):
    def __init__(self):
        return None
        

# Get some values from the Pulumi configuration (or use defaults)
config = pulumi.Config()

# Image Config
config_color = config.get("config_color", "red")

# ECR Config
ecr_user=config.get("ecrUser")
ecr_repo_name = "web_server_repo"

# EKS Config
min_cluster_size = config.get_float("minClusterSize", 3)
max_cluster_size = config.get_float("maxClusterSize", 6)
desired_cluster_size = config.get_float("desiredClusterSize", 3)
eks_node_instance_type = config.get("eksNodeInstanceType", "t3.medium")
vpc_network_cidr = config.get("vpcNetworkCidr", "10.0.0.0/16")

stack = pulumi.get_stack()

# Create an ECR resource for the Docker image built above
ecr_repo = aws.ecr.Repository(ecr_repo_name, name="docker-image-repo")
auth_token = aws.ecr.get_authorization_token_output(registry_id=ecr_repo.registry_id)

# Build backend Image
backend_image_name="flask_server"
backend_image = docker.Image("flask_server",
                        build=docker.DockerBuildArgs(
                            args={
                                "platform":"linux/arm64",
                                "env": f"CONFIG_COLOR={config_color}"
                            },
                            context=f"{os.getcwd()}/app"),
                        image_name=ecr_repo.repository_url.apply(lambda repository_url: f"{repository_url}:latest"),
                        registry=docker.RegistryArgs(
        username=ecr_user,
        password=pulumi.Output.secret(auth_token.password),
        server=ecr_repo.repository_url,
        ))

# Create a VPC for the EKS cluster
eks_vpc = awsx.ec2.Vpc("eks-vpc",
    enable_dns_hostnames=True,
    cidr_block=vpc_network_cidr)

# Create the EKS cluster
eks_cluster = eks.Cluster("eks-cluster",
    # Put the cluster in the new VPC created earlier
    vpc_id=eks_vpc.vpc_id,
    # Public subnets will be used for load balancers
    public_subnet_ids=eks_vpc.public_subnet_ids,
    # Private subnets will be used for cluster nodes
    private_subnet_ids=eks_vpc.private_subnet_ids,
    # Change configuration values to change any of the following settings
    instance_type=eks_node_instance_type,
    desired_capacity=desired_cluster_size,
    min_size=min_cluster_size,
    max_size=max_cluster_size,
    # Do not give worker nodes a public IP address
    node_associate_public_ip_address=False,
    # Change these values for a private cluster (VPN access required)
    endpoint_private_access=False,
    endpoint_public_access=True
    )

# Create a Kubernetes Deployment
app_labels = {'app': 'web-server'}
deployment = k8s.apps.v1.Deployment('web-server-dep',
                                    metadata=k8s.meta.v1.ObjectMetaArgs(labels=app_labels),
                                    spec=k8s.apps.v1.DeploymentSpecArgs(
                                        replicas=1,
                                        selector=k8s.meta.v1.LabelSelectorArgs(match_labels=app_labels),
                                        template=k8s.core.v1.PodTemplateSpecArgs(
                                            metadata=k8s.meta.v1.ObjectMetaArgs(labels=app_labels),
                                            spec=k8s.core.v1.PodSpecArgs(
                                                containers=[
                                                    k8s.core.v1.ContainerArgs(
                                                        name='myapp',
                                                        image=f'{ecr_repo.repository_url}:latest',
                                                        ports=[k8s.core.v1.ContainerPortArgs(name='http', container_port=80)]
                                                    )
                                                ]
                                            )
                                        )
                                    ),
                                    opts=pulumi.ResourceOptions(provider=eks_cluster.aws_provider)
                                    )

# Export values to use elsewhere
pulumi.export("kubeconfig", eks_cluster.kubeconfig)
pulumi.export("vpcId", eks_vpc.vpc_id)
