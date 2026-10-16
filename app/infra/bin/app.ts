#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { MinutasStack } from "../lib/minutas-stack";

const app = new cdk.App();

new MinutasStack(app, "LwMinutasDev", {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: "eu-west-1",
  },
  description: "Minutas dev stack. Fictional and published cases only.",
});
