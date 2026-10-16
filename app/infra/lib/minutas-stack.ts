import * as fs from "fs";
import * as path from "path";
import {
  Aspects,
  CfnOutput,
  Duration,
  Fn,
  IAspect,
  RemovalPolicy,
  Size,
  Stack,
  StackProps,
  Tags,
} from "aws-cdk-lib";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import * as authorizers from "aws-cdk-lib/aws-apigatewayv2-authorizers";
import * as integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as budgets from "aws-cdk-lib/aws-budgets";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as cloudtrail from "aws-cdk-lib/aws-cloudtrail";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3deploy from "aws-cdk-lib/aws-s3-deployment";
import * as sfn from "aws-cdk-lib/aws-stepfunctions";
import * as tasks from "aws-cdk-lib/aws-stepfunctions-tasks";
import { Construct, IConstruct } from "constructs";

const REGION = "eu-west-1";
const MODEL_ID = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0";
const INDEX_KEY = "index/fts.sqlite3";
const TEMPLATE_PATH = "app/engine/templates/decisao-arbitral-wiki.docx";
const LOCAL_ORIGIN = "http://localhost:5173";
const BUDGET_EMAIL = "xuyongdong0@gmail.com";

export class MinutasStack extends Stack {
  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    if (props?.env?.region && props.env.region !== REGION) {
      throw new Error("LwMinutasDev must target eu-west-1");
    }

    Tags.of(this).add("Project", "minutas");
    Tags.of(this).add("Environment", "dev");

    const lambdaDir = path.join(__dirname, "../../../build/lambda");
    if (!fs.existsSync(lambdaDir)) {
      throw new Error(
        `Lambda asset not found at ${lambdaDir}. Run: python app/infra/scripts/build_lambda.py`,
      );
    }

    const casesKey = new kms.Key(this, "CasesKey", {
      description: "Encrypts the Minutas cases bucket",
      enableKeyRotation: true,
      alias: "alias/lw-minutas-dev-cases",
      removalPolicy: RemovalPolicy.DESTROY,
      pendingWindow: Duration.days(7),
    });

    const casesBucket = new s3.Bucket(this, "CasesBucket", {
      bucketName: `lw-minutas-cases-${this.account}`,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: casesKey,
      bucketKeyEnabled: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: false,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const corpusBucket = new s3.Bucket(this, "CorpusBucket", {
      bucketName: `lw-minutas-corpus-${this.account}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: false,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const table = new dynamodb.Table(this, "Table", {
      partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "SK", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.DEFAULT,
      removalPolicy: RemovalPolicy.DESTROY,
      deletionProtection: false,
    });

    const code = lambda.Code.fromAsset(lambdaDir);
    const sharedEnv = {
      LW_TABLE: table.tableName,
      LW_CASES_BUCKET: casesBucket.bucketName,
      LW_CORPUS_BUCKET: corpusBucket.bucketName,
      LW_INDEX_S3_KEY: INDEX_KEY,
      LW_TEMPLATE_PATH: TEMPLATE_PATH,
      LW_MODEL_ID: MODEL_ID,
      LW_REGION: REGION,
    };

    const workerFn = new lambda.Function(this, "DraftWorkerFn", {
      functionName: "lw-minutas-draft-worker",
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.X86_64,
      handler: "app.api.worker.handle",
      code,
      memorySize: 1024,
      timeout: Duration.seconds(900),
      ephemeralStorageSize: Size.mebibytes(3072),
      environment: sharedEnv,
      logGroup: new logs.LogGroup(this, "DraftWorkerLogs", {
        retention: logs.RetentionDays.ONE_MONTH,
        removalPolicy: RemovalPolicy.DESTROY,
      }),
    });

    const invokeWorker = tasks.LambdaInvoke.jsonPath(this, "InvokeDraftWorker", {
      lambdaFunction: workerFn,
      payload: sfn.TaskInput.fromObject({
        caseId: sfn.JsonPath.stringAt("$.caseId"),
        draftId: sfn.JsonPath.stringAt("$.draftId"),
      }),
      retryOnServiceExceptions: false,
      taskTimeout: sfn.Timeout.duration(Duration.minutes(16)),
    });
    invokeWorker.addRetry({
      errors: [
        "Lambda.ServiceException",
        "Lambda.AWSLambdaException",
        "Lambda.SdkClientException",
        "Lambda.ClientExecutionTimeoutException",
        "Lambda.TooManyRequestsException",
      ],
      interval: Duration.seconds(2),
      maxAttempts: 6,
      backoffRate: 2,
    });

    const stateMachine = new sfn.StateMachine(this, "DraftRun", {
      stateMachineName: "DraftRun",
      stateMachineType: sfn.StateMachineType.STANDARD,
      definitionBody: sfn.DefinitionBody.fromChainable(invokeWorker),
      queryLanguage: sfn.QueryLanguage.JSON_PATH,
      timeout: Duration.minutes(16),
      tracingEnabled: false,
      comment: "Run one draft worker invocation for a fictional case.",
    });

    const apiFn = new lambda.Function(this, "ApiFn", {
      functionName: "lw-minutas-api",
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.X86_64,
      handler: "app.api.handler.handle",
      code,
      memorySize: 1024,
      timeout: Duration.seconds(30),
      ephemeralStorageSize: Size.mebibytes(3072),
      environment: {
        ...sharedEnv,
        LW_STATE_MACHINE_ARN: stateMachine.stateMachineArn,
      },
      logGroup: new logs.LogGroup(this, "ApiLogs", {
        retention: logs.RetentionDays.ONE_MONTH,
        removalPolicy: RemovalPolicy.DESTROY,
      }),
    });

    grantTableReadWrite(apiFn, table);
    grantTableReadWrite(workerFn, table);
    grantCasesReadWrite(apiFn, casesBucket, casesKey);
    grantCasesReadWrite(workerFn, casesBucket, casesKey);
    grantCorpusRead(apiFn, corpusBucket);
    grantCorpusRead(workerFn, corpusBucket);

    apiFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["states:StartExecution"],
        resources: [stateMachine.stateMachineArn],
      }),
    );

    workerFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel", "bedrock:Converse"],
        resources: [
          `arn:aws:bedrock:${REGION}:${this.account}:inference-profile/eu.*`,
          "arn:aws:bedrock:eu-*::foundation-model/*",
        ],
      }),
    );

    const httpApi = new apigwv2.HttpApi(this, "HttpApi", {
      apiName: "lw-minutas",
      description: "Minutas HTTP API",
      createDefaultStage: true,
    });

    const userPool = new cognito.UserPool(this, "UserPool", {
      userPoolName: "lw-minutas-dev",
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      mfa: cognito.Mfa.REQUIRED,
      mfaSecondFactor: { sms: false, otp: true, email: false },
      passwordPolicy: {
        minLength: 12,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true,
        tempPasswordValidity: Duration.days(7),
      },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      featurePlan: cognito.FeaturePlan.ESSENTIALS,
      removalPolicy: RemovalPolicy.DESTROY,
      deletionProtection: false,
    });

    const userPoolClient = userPool.addClient("WebClient", {
      userPoolClientName: "lw-minutas-web",
      generateSecret: false,
      authFlows: {
        userPassword: false,
        userSrp: false,
        adminUserPassword: false,
        custom: false,
      },
      preventUserExistenceErrors: true,
      enableTokenRevocation: true,
      supportedIdentityProviders: [cognito.UserPoolClientIdentityProvider.COGNITO],
      accessTokenValidity: Duration.hours(1),
      idTokenValidity: Duration.hours(1),
      refreshTokenValidity: Duration.days(30),
    });

    const authorizer = new authorizers.HttpJwtAuthorizer(
      "JwtAuthorizer",
      userPool.userPoolProviderUrl,
      {
        jwtAudience: [userPoolClient.userPoolClientId],
        identitySource: ["$request.header.Authorization"],
      },
    );

    httpApi.addRoutes({
      path: "/api/{proxy+}",
      methods: [apigwv2.HttpMethod.ANY],
      integration: new integrations.HttpLambdaIntegration("ApiIntegration", apiFn, {
        payloadFormatVersion: apigwv2.PayloadFormatVersion.VERSION_2_0,
        timeout: Duration.seconds(29),
      }),
      authorizer,
    });

    const webBucket = new s3.Bucket(this, "WebBucket", {
      bucketName: `lw-minutas-web-${this.account}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: false,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    // SPA routing on the web behaviour only, so /api/* error statuses reach the client unchanged.
    const spaRewrite = new cloudfront.Function(this, "SpaRewrite", {
      runtime: cloudfront.FunctionRuntime.JS_2_0,
      code: cloudfront.FunctionCode.fromInline(
        "function handler(event){var r=event.request;if(r.uri.indexOf('.')===-1){r.uri='/index.html';}return r;}",
      ),
    });

    const distribution = new cloudfront.Distribution(this, "WebDistribution", {
      comment: "Minutas dev",
      defaultRootObject: "index.html",
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(webBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
        functionAssociations: [
          { function: spaRewrite, eventType: cloudfront.FunctionEventType.VIEWER_REQUEST },
        ],
      },
      additionalBehaviors: {
        "/api/*": {
          origin: new origins.HttpOrigin(Fn.select(2, Fn.split("/", httpApi.apiEndpoint)), {
            protocolPolicy: cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
          }),
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        },
      },
    });

    const siteOrigin = `https://${distribution.distributionDomainName}`;
    const cfnCases = casesBucket.node.defaultChild as s3.CfnBucket;
    cfnCases.corsConfiguration = {
      corsRules: [
        {
          allowedMethods: ["PUT"],
          allowedOrigins: [siteOrigin, LOCAL_ORIGIN],
          allowedHeaders: ["*"],
          exposedHeaders: ["ETag"],
          maxAge: 3000,
        },
      ],
    };

    const userPoolDomain = userPool.addDomain("ManagedLogin", {
      cognitoDomain: { domainPrefix: `lw-minutas-${this.account}` },
      managedLoginVersion: cognito.ManagedLoginVersion.NEWER_MANAGED_LOGIN,
    });

    const redirectUrls = [`${siteOrigin}/`, `${LOCAL_ORIGIN}/`];
    const cfnClient = userPoolClient.node.defaultChild as cognito.CfnUserPoolClient;
    cfnClient.callbackUrLs = redirectUrls;
    cfnClient.logoutUrLs = redirectUrls;
    cfnClient.allowedOAuthFlows = ["code"];
    cfnClient.allowedOAuthFlowsUserPoolClient = true;
    cfnClient.allowedOAuthScopes = ["openid", "email", "profile"];
    cfnClient.supportedIdentityProviders = ["COGNITO"];
    cfnClient.addResourceDependency(userPoolDomain.node.defaultChild as cognito.CfnUserPoolDomain);

    const webDist = path.join(__dirname, "../../web/dist");
    const webSources: s3deploy.ISource[] = [];
    if (fs.existsSync(webDist) && fs.readdirSync(webDist).length > 0) {
      webSources.push(s3deploy.Source.asset(webDist, { exclude: ["config.json"] }));
    } else {
      webSources.push(
        s3deploy.Source.data(
          "index.html",
          "<!doctype html><html lang=\"pt\"><head><meta charset=\"utf-8\"><title>Minutas</title></head><body><p>MINUTA NÃO ASSINADA — AUXÍLIO À INVESTIGAÇÃO JURÍDICA</p></body></html>",
        ),
      );
    }
    webSources.push(
      s3deploy.Source.jsonData("config.json", {
        apiBase: "/api",
        region: REGION,
        userPoolId: userPool.userPoolId,
        clientId: userPoolClient.userPoolClientId,
        cognitoDomain: userPoolDomain.baseUrl(),
        redirectUri: `${siteOrigin}/`,
      }),
    );

    const webDeployment = new s3deploy.BucketDeployment(this, "WebDeployment", {
      sources: webSources,
      destinationBucket: webBucket,
      distribution,
      distributionPaths: ["/*"],
      memoryLimit: 256,
      prune: true,
    });
    Aspects.of(this).add(
      new ScopeCloudFrontInvalidation(
        `arn:aws:cloudfront::${this.account}:distribution/${distribution.distributionId}`,
      ),
    );

    const trailBucket = new s3.Bucket(this, "TrailBucket", {
      bucketName: `lw-minutas-trail-${this.account}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: false,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      lifecycleRules: [{ expiration: Duration.days(90) }],
      removalPolicy: RemovalPolicy.DESTROY,
    });

    new cloudtrail.Trail(this, "ManagementTrail", {
      trailName: "lw-minutas-dev",
      bucket: trailBucket,
      includeGlobalServiceEvents: true,
      isMultiRegionTrail: false,
      managementEvents: cloudtrail.ReadWriteType.ALL,
      sendToCloudWatchLogs: false,
      enableFileValidation: true,
    });

    new budgets.CfnBudget(this, "MonthlyCostBudget", {
      budget: {
        budgetName: "lw-minutas-dev-monthly",
        budgetType: "COST",
        timeUnit: "MONTHLY",
        budgetLimit: { amount: 10, unit: "USD" },
      },
      notificationsWithSubscribers: [
        {
          notification: {
            comparisonOperator: "GREATER_THAN",
            notificationType: "ACTUAL",
            threshold: 80,
            thresholdType: "PERCENTAGE",
          },
          subscribers: [{ subscriptionType: "EMAIL", address: BUDGET_EMAIL }],
        },
        {
          notification: {
            comparisonOperator: "GREATER_THAN",
            notificationType: "FORECASTED",
            threshold: 100,
            thresholdType: "PERCENTAGE",
          },
          subscribers: [{ subscriptionType: "EMAIL", address: BUDGET_EMAIL }],
        },
      ],
    });

    new CfnOutput(this, "WebUrl", { value: `${siteOrigin}/` });
    new CfnOutput(this, "UserPoolId", { value: userPool.userPoolId });
    new CfnOutput(this, "UserPoolClientId", { value: userPoolClient.userPoolClientId });
    new CfnOutput(this, "CognitoDomainUrl", { value: userPoolDomain.baseUrl() });
    new CfnOutput(this, "ApiEndpoint", { value: httpApi.apiEndpoint });
    const casesBucketOut = new CfnOutput(this, "CasesBucketOutput", { value: casesBucket.bucketName });
    casesBucketOut.overrideLogicalId("CasesBucket");
    const corpusBucketOut = new CfnOutput(this, "CorpusBucketOutput", { value: corpusBucket.bucketName });
    corpusBucketOut.overrideLogicalId("CorpusBucket");
    new CfnOutput(this, "TableName", { value: table.tableName });
    new CfnOutput(this, "StateMachineArn", { value: stateMachine.stateMachineArn });
  }
}

function grantTableReadWrite(fn: lambda.Function, table: dynamodb.Table): void {
  fn.addToRolePolicy(
    new iam.PolicyStatement({
      actions: [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query",
        "dynamodb:BatchGetItem",
        "dynamodb:BatchWriteItem",
        "dynamodb:ConditionCheckItem",
      ],
      resources: [table.tableArn],
    }),
  );
}

function grantCasesReadWrite(fn: lambda.Function, bucket: s3.Bucket, key: kms.IKey): void {
  fn.addToRolePolicy(
    new iam.PolicyStatement({
      actions: ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      resources: [bucket.arnForObjects("*")],
    }),
  );
  // Without ListBucket, S3 answers a missing key with 403 instead of 404.
  fn.addToRolePolicy(
    new iam.PolicyStatement({ actions: ["s3:ListBucket"], resources: [bucket.bucketArn] }),
  );
  key.grantEncryptDecrypt(fn);
}

class ScopeCloudFrontInvalidation implements IAspect {
  constructor(private readonly distributionArn: string) {}

  visit(node: IConstruct): void {
    if (!(node instanceof iam.CfnPolicy) || !node.node.path.includes("CDKBucketDeployment")) {
      return;
    }
    const rendered = (
      node.policyDocument as {
        toJSON(): { Statement?: Array<{ Action?: string | string[] }> };
      }
    ).toJSON();
    for (const [index, statement] of (rendered.Statement ?? []).entries()) {
      const actions = Array.isArray(statement.Action) ? statement.Action : [statement.Action];
      if (actions.includes("cloudfront:CreateInvalidation")) {
        node.addPropertyOverride(`PolicyDocument.Statement.${index}.Resource`, this.distributionArn);
      }
    }
  }
}

function grantCorpusRead(fn: lambda.Function, bucket: s3.Bucket): void {
  fn.addToRolePolicy(
    new iam.PolicyStatement({
      actions: ["s3:GetObject"],
      resources: [bucket.arnForObjects(INDEX_KEY)],
    }),
  );
}
