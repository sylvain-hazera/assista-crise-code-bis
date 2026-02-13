export interface User {
  id?: number;
  login?: string;
  hashPassword: string;
  userType: UserRole;
  lastName: string;
  firstName?: string;
  pseudo?: string;
  email: string;
  phone: string;
  postalCode: string;
  emailVerified?: boolean;
  enable?: boolean;
  avatar?: string;
  createdAt?: Date;
  updatedAt?: Date;
  token?: string;
}

// export interface Utilisateur {
//   id?: string;
//   username: string;
//   email: string;
//   type: 'ADMIN' | 'AUT_LOCALE' | 'SECOURS' | 'UTIL_SIMPLE';
//   photo?: string;
//   telephone_utilisateur?: string;
// }

export enum UserRole {
  Individual = 'individual',
  Organization = 'organization',
  Rescue = 'rescue',
  Admin = 'admin'
}